# Question 1 — SupportCopilot Solution

## What Was Causing the High Cost?
The original baseline was averaging **8,868 points per ticket** (target is **≤ 3,000 points**). Looking at `build_messages()` and the billing formula, the high cost came down to two simple things:

1. **Paying for reasoning nobody reads:** The prompt asked the model to *"think step by step"* and *"write full reasoning"*. Because output tokens cost 5× more than input tokens ($15\text{ pts}$ vs $3\text{ pts}$), generating 480+ tokens of explanation burned over $7,200\text{ points}$ per call. But downstream, `parse_resolution()` only parses the JSON block—so all that explanation text was just thrown away.
2. **Dynamic UUID in the prompt:** Injected `uuid.uuid4()` at the start of every prompt. Even though our prompt is under the 1,024-token cache threshold, putting random IDs in prompt headers is bad practice because it breaks prefix caching.

---

## What I Changed
In `question1/agent.py`:
- **Removed the UUID prefix:** Kept the prompt header deterministic and clean.
- **Removed the verbose reasoning instruction:** The existing `_FEW_SHOT` examples already demonstrate the required JSON schema (`action`, `kb_article`, `customer_reply`). Without the instruction to write reasoning paragraphs, the model directly outputs the clean JSON response (~40 tokens).
- **Kept the KB and few-shots intact:** This ensured classification accuracy stayed at 100% with zero policy regressions.

---

## Token & Points Breakdown for Ticket T-1001

| Metric | Baseline | Optimized | Difference |
| :--- | :---: | :---: | :---: |
| **Input Tokens** | 520 tok | **469 tok** | -51 tokens |
| **Output Tokens** | 487 tok | **46 tok** | **-441 tokens (-90.5%)** |
| **Input Cost ($3\text{ pts/tok}$)** | 1,560 pts | 1,407 pts | -153 pts |
| **Output Cost ($15\text{ pts/tok}$)** | 7,305 pts | 690 pts | **-6,615 pts** |
| **Total Points** | **8,865 pts** | **2,097 pts** | **-76.3% cheaper** |

---

## Results Across All Tickets

| Ticket | Scenario | Baseline Points | Optimized Points | Action Picked | Policy Match |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **T-1001** | Refund (physical, unopened) | 8,865 pts | 2,097 pts | `REFUND` | ✅ |
| **T-1002** | Refund (digital license revealed) | 8,844 pts | 1,974 pts | `SEND_ARTICLE` | ✅ |
| **T-1003** | Replacement (custom item) | 8,871 pts | 1,935 pts | `ESCALATE_TIER2` | ✅ |
| **T-1004** | Replacement (catalog item) | 8,892 pts | 1,896 pts | `REPLACE` | ✅ |
| **Total** | **4 Tickets** | **35,472 pts** | **7,902 pts** | **-77.7% reduction** | ✅ |
| **Average** | **Per Ticket** | **8,868 pts** | **1,975 pts** | **Target: ≤ 3,000 pts** | ✅ |

### Accuracy & Holdout Verification
- **Public Tickets:** All 4 tickets pick the exact correct action and cite the right KB article.
- **Holdout Ticket `T-1091`:** The holdout subscription ticket passed on the first run (`SEND_ARTICLE` with `subscription-cooling-off`), showing that dropping the reasoning text didn't hurt decision quality at all.

---

## Why Prompt Caching Was Left Out Here
The billing rules state that prompt caching requires an **identical prefix of ≥ 1,024 tokens**.
- In Question 1, our entire static prefix (persona + few-shot examples + all 5 KB articles) is only **~375 tokens**.
- Because 375 tokens is well under the 1,024 threshold, caching simply cannot trigger here.
- Artificially padding the prompt with 650+ tokens of meaningless filler just to trigger the cache threshold would actually backfire: the first call would cost $1,024 \times 3 = 3,072\text{ pts}$ on input alone, wiping out any downstream savings.

### When Would Caching Make Sense?
Prompt caching becomes a game-changer when you have a **real, large knowledge base** (e.g., 20+ detailed policy guides, product manuals, or shipping terms) that naturally exceeds 1,024 tokens of meaningful text. In that scenario, keeping the static knowledge base at the top of the prompt allows all subsequent requests to read it at **0.3 pts/token instead of 3 pts/token (a 90% discount on input)**. *(This is the exact lever we explore in Question 2).*

---

## Key Engineering Takeaways
1. **Output Token Leverage (15:3 Price Asymmetry):** Output tokens cost 5× more than input tokens. Trimming 440 output tokens delivered far more cost reduction than any micro-optimization on the input prompt ever could.
2. **Align the Prompt with the Consumer:** If your application code parses structured JSON (`json.loads()`), asking the LLM for natural-language chain-of-thought is pure financial waste.
3. **Resist Over-Engineering (No RAG Needed for 5 Docs):** With only 5 help-center articles (~220 tokens total), dumping them directly into context costs just 660 points. Building a mini-retriever or vector search for 5 articles would add latency and brittle failure modes (like failing on unseen edge cases such as holdout `T-1091`) for negligible token savings.
