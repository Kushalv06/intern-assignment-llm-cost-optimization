from __future__ import annotations

import json
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

from question1.agent import parse_resolution


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """Same product as Question 1 — triage, retrieve, compose, audit."""

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = format_thread(ticket)
        snapshot = json.dumps(order, indent=2)

        triage = self._triage(thread, order)
        if triage is None:
            # Zero-token short-circuit: escalate unknown queries without calling the LLM
            return TicketResolution("ESCALATE_TIER2", "returns-within-30-days")

        retrieved = self._retrieve(triage)
        draft = self._compose(ticket_id, thread, snapshot, triage, retrieved)
        return self._audit(draft)

    def _triage(self, thread: str, order_data: dict) -> str | None:
        """Classifies the ticket intent from customer message & order flags."""
        text = thread.lower()
        if order_data.get("license_revealed"):
            return "digital"
        if "damaged" in text or "cracked" in text or order_data.get("damage_reported"):
            return "damage"
        if order_data.get("product_type") == "subscription":
            return "subscription"
        if "return" in text or "refund" in text or order_data.get("product_type") == "physical":
            return "return"
        return None

    def _retrieve(self, triage: str) -> str:
        """Fetch only the specific KB articles matching the triage intent."""
        category_map = {
            "digital": ["digital-license-no-refund"],
            "damage": ["damage-replacement-7-days", "custom-items-no-replace"],
            "subscription": ["subscription-cooling-off"],
            "return": ["returns-within-30-days"],
        }
        target_articles = category_map.get(triage, ["returns-within-30-days"])
        return "\n\n".join(f"[{aid}]\n{load_article(aid)}" for aid in target_articles)

    def _compose(
        self,
        ticket_id: str,
        thread: str,
        snapshot: str,
        triage: str,
        retrieved: str,
    ) -> str:
        messages = [
            ChatMessage(
                "system",
                "ShopAssist Tier-1 agent. Use the retrieved knowledge base to resolve the ticket. "
                "Compose node: JSON with action, kb_article, customer_reply.",
            ),
            ChatMessage(
                "user",
                "\n\n".join(
                    [
                        f"TICKET {ticket_id}",
                        f"THREAD:\n{thread}",
                        f"ORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT",
                        f"TRIAGE:\n{triage}",
                        f"ARTICLES:\n{retrieved}",
                    ]
                ),
            ),
        ]
        return self.llm.chat("compose", messages)

    def _audit(
        self,
        draft: str,
    ) -> TicketResolution:
        """Deterministic guardrail: validates action schema."""
        valid_actions = {"REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2"}
        p = parse_resolution(draft)
        action = p.action if p.action in valid_actions else "ESCALATE_TIER2"
        return TicketResolution(action, p.kb_article)
        
