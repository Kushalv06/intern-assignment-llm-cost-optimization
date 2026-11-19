# Question 2 — SupportPipeline Solution

## What Was Causing the High Cost?

Running the original baseline pipeline on public tickets produced **73,374 points for T-1001** and **73,347 points for T-1002** (the assignment target is **≤ 2,500 points**). Tracing the execution revealed three primary causes for the cost:

1. **Four Sequential LLM Calls with Verbose Prompts:** The baseline made four separate calls per ticket (`triage` → `retrieve` → `compose` → `audit`). Three of these calls were prompted with verbose triggers (`"step by step"`, `"full reasoning"`, `"double-check"`), generating ~480–495 output tokens each. Across the four calls, the baseline generated **1,502 output tokens ($22,530\text{ points}$)** per ticket.
2. **Context Stuffing:** `_triage` injected 120,000 characters of the expanded help center (8,457 input tokens), and `_audit` injected 80,000 characters (6,711 input tokens). Across all four calls, input tokens totaled **16,948 tokens ($50,844\text{ points}$)**.
3. **Payload Duplication:** `_compose` passed `triage` twice into the prompt (literally labeled `"TRIAGE AGAIN"`), paying twice for the same text.

*(Note on local startup: `SupportPipeline.__init__()` also called `expanded_help_center_blob()`, which ran an $O(N^2)$ tokenization loop to build a 210,000-token string, freezing process startup for ~40 seconds. Avoiding this call in our final solution eliminates this local startup delay).*

---

## What I Changed (Pipeline Re-Architecture)

Instead of paying for four LLM calls when only one is needed for the final decision, I converted three stages into deterministic Python code and kept one concise LLM generation call:

1. **`_triage` (Python — 0 pts):** Reads customer message text and order flags to categorize the intent (`"digital"`, `"damage"`, `"subscription"`, or `"return"`).
2. **`_retrieve` (Targeted RAG in Python — 0 pts):** Uses the triage category to load only the 1–2 relevant policy articles using `load_article()`. Instead of loading thousands of tokens of warehouse notes, it retrieves ~50 tokens of policy text.
3. **`_compose` (The Single LLM Call — ~1,230–1,377 pts):** Prompted cleanly without verbose triggers to output concise JSON (`action`, `kb_article`, `customer_reply`), reducing output from 1,502 tokens to ~36–46 tokens.
4. **`_audit` (Python Guardrail — 0 pts):** Parses the JSON and checks that `action` belongs to `VALID_ACTIONS` (defaulting safely to `"ESCALATE_TIER2"` if invalid).

---

## Points Breakdown for Two Required Tickets

### 1. Physical Fulfillment Path: Ticket `T-1001` (Unopened Return → `REFUND`)
* **Scenario:** Customer wants to return unopened wireless headphones delivered 10 days ago.
* **Resolution:** `action`: `REFUND` | `kb_article`: `returns-within-30-days`

| Metric | Baseline (Measured) | Optimized (Measured) | Difference |
| :--- | :---: | :---: | :---: |
| **LLM Calls** | 4 calls | **1 call** | -3 calls |
| **Input Tokens** | 16,948 tok | **229 tok** | -16,719 tokens |
| **Output Tokens** | 1,502 tok | **46 tok** | -1,456 tokens |
| **Input Cost ($3\text{ pts/tok}$)** | 50,844 pts | 687 pts | -50,157 pts |
| **Output Cost ($15\text{ pts/tok}$)** | 22,530 pts | 690 pts | -21,840 pts |
| **Total Points** | **73,374 pts** | **1,377 pts** | **-98.1% reduction** |

#### Baseline per-call breakdown for `T-1001`:
* `triage`: 8,457 in | 485 out | 32,646 pts
* `retrieve`: 593 in | 46 out | 2,469 pts
* `compose`: 1,187 in | 483 out | 10,806 pts
* `audit`: 6,711 in | 488 out | 27,453 pts

---

### 2. Denial / Escalation Path: Ticket `T-1002` (Software Key → `SEND_ARTICLE`)
* **Scenario:** Customer requests a refund for a software license key that has already been viewed.
* **Resolution:** `action`: `SEND_ARTICLE` | `kb_article`: `digital-license-no-refund`

| Metric | Baseline (Measured) | Optimized (Measured) | Difference |
| :--- | :---: | :---: | :---: |
| **LLM Calls** | 4 calls | **1 call** | -3 calls |
| **Input Tokens** | 16,909 tok | **215 tok** | -16,694 tokens |
| **Output Tokens** | 1,508 tok | **39 tok** | -1,469 tokens |
| **Input Cost ($3\text{ pts/tok}$)** | 50,727 pts | 645 pts | -50,082 pts |
| **Output Cost ($15\text{ pts/tok}$)** | 22,620 pts | 585 pts | -22,035 pts |
| **Total Points** | **73,347 pts** | **1,230 pts** | **-98.3% reduction** |

#### Baseline per-call breakdown for `T-1002`:
* `triage`: 8,449 in | 480 out | 32,547 pts
* `retrieve`: 591 in | 39 out | 2,358 pts
* `compose`: 1,164 in | 495 out | 10,917 pts
* `audit`: 6,705 in | 494 out | 27,525 pts

---

## Results Across All Public Tickets

All measurements below are produced from a single run of `python question2/run.py` on the final code:

| Ticket | Scenario | Baseline Points | Optimized Points | Input Tok | Output Tok | Action Picked | Policy Match |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :---: |
| **T-1001** | Physical return (unopened) | 73,374 pts | 1,377 pts | 229 | 46 | `REFUND` | ✅ |
| **T-1002** | Digital license (revealed) | 73,347 pts | 1,230 pts | 215 | 39 | `SEND_ARTICLE` | ✅ |
| **T-1003** | Custom item (damaged) | ~73,000 pts | 1,302 pts | 239 | 39 | `ESCALATE_TIER2` | ✅ |
| **T-1004** | Stock physical item (damaged) | ~73,000 pts | 1,263 pts | 241 | 36 | `REPLACE` | ✅ |
| **Total** | **4 Public Tickets** | **~292,000 pts** | **5,172 pts** | **924** | **160** | **-98.2%** | ✅ |
| **Average** | **Per Ticket** | **~73,000 pts** | **1,293 pts** | **231** | **40** | **Target: ≤ 2,500 pts** | ✅ |

*(Verification on holdout ticket `data/tickets/T-1091.json`: resolves to `SEND_ARTICLE` with `subscription-cooling-off` in 1,221 points, confirming that the category mapping handles subscription policies correctly).*

---

## Why Targeted Context Pruning Beat Prompt Caching Here

Under the billing simulator rules, prompt caching requires a static prefix of **≥ 1,024 tokens**.
1. **The 210,000-token corpus cannot be stuffed into context:** Even with a 100% prompt cache hit at $0.3\text{ pts/tok}$, 210,000 tokens costs **63,000 points**—which exceeds the 2,500-point budget by $25\times$.
2. **Context Pruning > Prompt Caching:** Padding the prompt with 800 tokens of artificial filler just to reach the 1,024-token cache threshold would cost 730 input points ($1,036 \times 0.3 + 140 \times 3$) instead of 660 input points ($220 \times 3$)—paying more just to transmit useless text.

---

## Key Engineering Takeaways

1. **Node Pruning in Agent Pipelines:** Multi-node agent architectures often suffer from compounding token costs. Converting redundant LLM calls (`triage`, `retrieve`, `audit`) into zero-cost deterministic Python code removed three sequential network round-trips and cut 1,456 output tokens per ticket.
2. **RAG Over Context Stuffing:** When an enterprise knowledge base exceeds the token budget, intelligent indexing and retrieval is the only viable path.
3. **Deterministic Guardrails:** Use Python code (schema parsing, enum validation) for output audit checks rather than paying an expensive LLM call to verify another LLM's JSON.
