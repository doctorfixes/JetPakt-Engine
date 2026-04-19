"""Inbox-scan planner and classifier.

Design: The CLI cannot call connectors. It produces two artifacts that the
main agent uses:

  1. `inbox_query_plan.json` — list of Outlook `search_email` queries the
     agent should run (one per prospect domain + generic bounce queries).

  2. `inbox_apply_plan.json` — built by the agent after it feeds raw
     search hits back to `classify_hits()`. Lists Sheet actions:
       - Outreach Log updates (reply_received_at, reply_sentiment, result)
       - Prospects row stage flips (Replied / Disqualified)
       - Suppression tab appends

The classification is pure-Python deterministic: sender domain matching +
bounce-token matching + unsubscribe-token matching. The agent provides the
raw hits; the CLI decides what to do.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import (
    SHEET_ID, SHEET_URL, WORKSHEET_IDS,
    BOUNCE_SUBJECT_TOKENS, BOUNCE_FROM_TOKENS, UNSUB_TOKENS,
)
from .sync import now_iso

EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")


def extract_domain(email: str) -> str:
    """Return lowercased domain part, or '' if not parseable."""
    if not email:
        return ""
    m = EMAIL_RE.search(email.strip().lower())
    return m.group(1) if m else ""


@dataclass
class Prospect:
    prospect_id: str
    business_name: str
    owner_email: str
    stage: str
    legal_severity: str = ""

    @property
    def domain(self) -> str:
        return extract_domain(self.owner_email)


def build_query_plan(prospects: List[Prospect], lookback_days: int = 3) -> dict:
    """Emit the list of Outlook search_email queries for the cron run.

    The agent runs each query via outlook.search_email and stores the raw
    results for classify_hits().
    """
    seen_domains = set()
    queries = []
    for p in prospects:
        d = p.domain
        if not d or d in seen_domains:
            continue
        seen_domains.add(d)
        queries.append({
            "query": f"from:@{d}",
            "prospect_id": p.prospect_id,
            "business_name": p.business_name,
            "domain": d,
            "kind": "reply_probe",
        })
    # Generic bounce queries (one is plenty — postmaster + undeliverable).
    queries.append({
        "query": "from:postmaster OR from:mailer-daemon OR subject:undeliverable",
        "kind": "bounce_probe",
    })
    return {
        "generated_at": now_iso(),
        "lookback_days": lookback_days,
        "prospect_count": len(prospects),
        "domain_count": len(seen_domains),
        "queries": queries,
    }


@dataclass
class Hit:
    """Normalised search_email result, produced by the agent from raw hits."""
    message_id: str
    from_email: str
    from_name: str
    subject: str
    received_at: str  # ISO
    body_preview: str
    to_list: List[str]  # addresses this message was sent to


@dataclass
class Classification:
    prospect_id: str
    business_name: str
    domain: str
    hit: Hit
    kind: str  # 'reply' | 'bounce' | 'unsubscribe' | 'ignore'
    sentiment: str  # 'positive' | 'neutral' | 'negative' | ''
    rationale: str


def _match_unsub(text: str) -> bool:
    t = text.lower()
    return any(tok in t for tok in UNSUB_TOKENS)


def _match_bounce_sender(from_email: str) -> bool:
    e = (from_email or "").lower()
    return any(tok in e for tok in BOUNCE_FROM_TOKENS)


def _match_bounce_subject(subject: str) -> bool:
    s = (subject or "").lower()
    return any(tok in s for tok in BOUNCE_SUBJECT_TOKENS)


def _sentiment(body: str) -> str:
    t = (body or "").lower()
    # Extremely simple keyword sentiment. Intent here is flag-for-review, not
    # perfect classification — the human still reviews.
    positive = ("yes", "interested", "send me", "would like", "tell me more",
                "sure", "sounds good", "please do")
    negative = ("no thanks", "not interested", "remove me", "unsubscribe",
                "stop", "wrong number", "not a fit", "please don't")
    pos_hit = any(k in t for k in positive)
    neg_hit = any(k in t for k in negative)
    if pos_hit and not neg_hit:
        return "positive"
    if neg_hit and not pos_hit:
        return "negative"
    return "neutral"


def classify_hit(hit: Hit, prospects_by_domain: Dict[str, Prospect]) -> Classification:
    """Classify a single inbox hit against the prospect roster."""
    sender_domain = extract_domain(hit.from_email)
    # Bounce detection first — postmaster messages often quote the original
    # recipient in the body/to_list.
    if _match_bounce_sender(hit.from_email) or _match_bounce_subject(hit.subject):
        # Try to recover the original prospect by scanning body + to_list for a known domain.
        blob = f"{hit.body_preview}\n{' '.join(hit.to_list or [])}".lower()
        matched = ""
        business = ""
        pid = ""
        for domain, p in prospects_by_domain.items():
            if domain and domain in blob:
                matched = domain
                business = p.business_name
                pid = p.prospect_id
                break
        return Classification(
            prospect_id=pid, business_name=business, domain=matched,
            hit=hit, kind="bounce", sentiment="",
            rationale=f"bounce signal from={hit.from_email!r} subject={hit.subject!r}",
        )

    # Normal reply — match sender domain to a prospect.
    p = prospects_by_domain.get(sender_domain)
    if not p:
        return Classification(
            prospect_id="", business_name="", domain=sender_domain,
            hit=hit, kind="ignore", sentiment="",
            rationale=f"no prospect match for domain {sender_domain!r}",
        )

    if _match_unsub(hit.body_preview) or _match_unsub(hit.subject):
        return Classification(
            prospect_id=p.prospect_id, business_name=p.business_name, domain=sender_domain,
            hit=hit, kind="unsubscribe", sentiment="negative",
            rationale="unsubscribe intent detected",
        )

    return Classification(
        prospect_id=p.prospect_id, business_name=p.business_name, domain=sender_domain,
        hit=hit, kind="reply", sentiment=_sentiment(hit.body_preview),
        rationale=f"sender domain {sender_domain!r} matches prospect",
    )


def build_apply_plan(classifications: List[Classification]) -> dict:
    """Given classified hits, emit the Sheet actions the agent applies."""
    ts = now_iso()
    prospect_updates = []
    outreach_log_appends = []
    suppression_appends = []
    seen_suppressed = set()

    for c in classifications:
        if c.kind == "ignore":
            continue

        if c.kind in ("reply", "unsubscribe"):
            # Append a new inbound-row to Outreach Log documenting the reply.
            outreach_log_appends.append({
                "spreadsheetId": SHEET_ID,
                "worksheetId": WORKSHEET_IDS["Outreach Log"],
                "row_object": {
                    "log_id": f"log_{ts[:10]}_reply_{c.prospect_id[:20]}",
                    "prospect_id": c.prospect_id,
                    "direction": "inbound",
                    "channel": "outlook",
                    "touch_type": "reply" if c.kind == "reply" else "unsubscribe",
                    "template_version": "",
                    "subject": c.hit.subject,
                    "body_excerpt": (c.hit.body_preview or "")[:240],
                    "draft_file": "",
                    "pillar": "",
                    "case_id": "",
                    "sent_at": "",
                    "reply_received_at": c.hit.received_at,
                    "reply_sentiment": c.sentiment,
                    "result": "replied" if c.kind == "reply" else "unsubscribed",
                    "created_at": ts,
                },
            })
            # Flip the prospect stage.
            prospect_updates.append({
                "spreadsheetId": SHEET_ID,
                "worksheetId": WORKSHEET_IDS["Prospects"],
                "find": {"column": "A", "value": c.prospect_id},
                "set": {
                    "stage": "Disqualified" if c.kind == "unsubscribe" else "Replied",
                    "updated_at": ts,
                    "notes_append": (
                        f"[{ts[:10]}] {'unsubscribe' if c.kind == 'unsubscribe' else 'reply'} "
                        f"received from {c.domain}; sentiment={c.sentiment}"
                    ),
                },
            })
            if c.kind == "unsubscribe" and c.domain not in seen_suppressed:
                seen_suppressed.add(c.domain)
                suppression_appends.append({
                    "spreadsheetId": SHEET_ID,
                    "worksheetId": WORKSHEET_IDS["Suppression"],
                    "row_object": {
                        "email_or_domain": c.hit.from_email or c.domain,
                        "type": "email",
                        "reason": "unsubscribe reply",
                        "prospect_id": c.prospect_id,
                        "suppressed_at": ts,
                        "source": "inbox_scan",
                    },
                })
        elif c.kind == "bounce":
            prospect_updates.append({
                "spreadsheetId": SHEET_ID,
                "worksheetId": WORKSHEET_IDS["Prospects"],
                "find": {"column": "A", "value": c.prospect_id} if c.prospect_id else None,
                "set": {
                    "stage": "Disqualified",
                    "updated_at": ts,
                    "notes_append": f"[{ts[:10]}] bounce detected; suppressing domain {c.domain or '?'}",
                },
            })
            outreach_log_appends.append({
                "spreadsheetId": SHEET_ID,
                "worksheetId": WORKSHEET_IDS["Outreach Log"],
                "row_object": {
                    "log_id": f"log_{ts[:10]}_bounce_{(c.prospect_id or c.domain or 'unk')[:20]}",
                    "prospect_id": c.prospect_id,
                    "direction": "inbound",
                    "channel": "outlook",
                    "touch_type": "bounce",
                    "template_version": "",
                    "subject": c.hit.subject,
                    "body_excerpt": (c.hit.body_preview or "")[:240],
                    "draft_file": "",
                    "pillar": "",
                    "case_id": "",
                    "sent_at": "",
                    "reply_received_at": c.hit.received_at,
                    "reply_sentiment": "",
                    "result": "bounced",
                    "created_at": ts,
                },
            })
            if c.domain and c.domain not in seen_suppressed:
                seen_suppressed.add(c.domain)
                suppression_appends.append({
                    "spreadsheetId": SHEET_ID,
                    "worksheetId": WORKSHEET_IDS["Suppression"],
                    "row_object": {
                        "email_or_domain": c.domain,
                        "type": "domain",
                        "reason": "hard bounce",
                        "prospect_id": c.prospect_id,
                        "suppressed_at": ts,
                        "source": "inbox_scan",
                    },
                })

    return {
        "generated_at": ts,
        "sheet_id": SHEET_ID,
        "sheet_url": SHEET_URL,
        "summary": {
            "replies": sum(1 for c in classifications if c.kind == "reply"),
            "unsubscribes": sum(1 for c in classifications if c.kind == "unsubscribe"),
            "bounces": sum(1 for c in classifications if c.kind == "bounce"),
            "ignored": sum(1 for c in classifications if c.kind == "ignore"),
        },
        "prospect_updates": [u for u in prospect_updates if u.get("find") is not None],
        "outreach_log_appends": outreach_log_appends,
        "suppression_appends": suppression_appends,
    }


def load_prospects_from_json(path: Path) -> List[Prospect]:
    """Load prospects from a simple JSON file.

    Expected shape: [{"prospect_id": ..., "business_name": ...,
                      "owner_email": ..., "stage": ..., "legal_severity": ""}]
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Prospect(**d) for d in data]


def prospects_by_domain(prospects: List[Prospect]) -> Dict[str, Prospect]:
    out: Dict[str, Prospect] = {}
    for p in prospects:
        d = p.domain
        if d and d not in out:
            out[d] = p
    return out
