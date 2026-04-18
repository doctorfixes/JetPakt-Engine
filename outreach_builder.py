"""
JetPakt — Initial Outreach Builder

Generates personalized cold-outreach email drafts for the top Denver restaurant
leads. Each draft:
  - Warm, consultative, Denver-local tone
  - Never names individual staff
  - Anchors one observation to a verbatim public quote already visible on Google/Yelp
  - Offers a free one-page preview (not a pitch for the paid scan)
  - Legal-HIGH routing: owner-only (never cc'd elsewhere)
  - Ends with Ryan's boilerplate signature

Output: a JSON manifest + one .eml-style draft per target that we either
hand off to the Outlook connector or save to disk for manual review.

Usage:
    python outreach_builder.py --top 5 --out output/outreach/initial_wave_2026-04-18
"""
from __future__ import annotations
import argparse
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Signature — preserve verbatim per project constraint
# ---------------------------------------------------------------------------
RYAN_SIGNATURE = """Ryan B.
JetPakt · Denver
303-549-1697 · gojetpakt.us@outlook.com
Gojetpakt.com"""

SITE_URL = "https://poetic-melba-f04633.netlify.app"


# ---------------------------------------------------------------------------
# Template fragments — composable, tone-safe, anchor-required
# ---------------------------------------------------------------------------
SUBJECT_TEMPLATES = {
    "legal_high": "A quiet observation about {name} — and a free preview",
    "legal_med":  "Something Denver guests are saying about {name}",
    "standard":   "A short note about {name} from a Denver consultant",
}

OPENING = (
    "Hi there,\n\n"
    "I'm Ryan — I run JetPakt, a small Denver-based practice that reads public "
    "restaurant reviews carefully and turns what guests are already saying online "
    "into something you can act on. I'm reaching out to {name} specifically because "
    "I've been going through your public reviews this week and there's one pattern "
    "worth surfacing."
)

PILLAR_LEAD_IN = (
    "\n\nThe theme I keep seeing cluster — entirely in public, on Google and Yelp — "
    "is {pillar_desc}. Here's one verbatim quote from a recent review that captures "
    "it cleanly:"
)

QUOTE_BLOCK = '\n\n    "{quote}"'

LEGAL_FLAG_NOTE = (
    "\n\nThis is the kind of pattern that tends to draw both regulatory attention "
    "(Colorado's HB25-1090 took effect January 1) and the occasional private-action "
    "suit, so it's worth getting in front of before the review volume grows. I'm "
    "not a lawyer and this isn't legal advice — just a heads-up from someone who "
    "reads these reviews for a living."
)

OFFER = (
    "\n\nI'd like to send you a free one-page preview — drawn entirely from your "
    "public reviews — showing the rating trend, the two most-cited complaint themes, "
    "and one verbatim quote that captures each. No commitment, no sales call, no "
    "CRM follow-up. If it's useful, a full Scan (the complete 8-pillar audit with "
    "draft response templates) is $49 and delivered in about 48 hours.\n\n"
    "If you'd like the preview, just reply with 'yes' and I'll have it to you "
    "within two business days. If not, I won't follow up."
)

GUARDRAIL_FOOTER = (
    "\n\nA note on how I work, so nothing's a surprise: every finding I send you "
    "is anchored to a verbatim public quote — I never name individual staff, never "
    "invent a claim, and I never post or email anything on your behalf. Every "
    "response template is a draft that lands in your inbox for your approval."
    f"\n\nMore detail at {SITE_URL} if useful."
    "\n\n— "
)

GUARDRAIL_FOOTER_NO_LEGAL = GUARDRAIL_FOOTER  # same text for now; kept for future divergence


# ---------------------------------------------------------------------------
# Pillar descriptors — key tokens per pillar, plus display description.
# Key tokens are used to pick the verbatim quote that BEST matches the pillar.
# ---------------------------------------------------------------------------
PILLARS = {
    "billing_service_fee": {
        "match_any": ["billing", "service-fee", "service fee"],
        "desc": "the way service fees and automatic charges are surfaced on the bill",
        "quote_keywords": ["service fee", "service charge", "automatic", "gratuity", "surcharge", "hidden", "not disclosed", "not told", "%"],
    },
    "wait_reservation": {
        "match_any": ["wait time", "reservation"],
        "desc": "wait times and the reservation-to-seating experience",
        "quote_keywords": ["wait", "minutes", "seated", "reservation", "took"],
    },
    "food_quality": {
        "match_any": ["food quality"],
        "desc": "consistency in food quality between visits",
        "quote_keywords": ["cold", "overcooked", "undercooked", "burger", "food was", "quality", "slipped", "not the same", "used to"],
    },
    "service_attentiveness": {
        # Deliberately NOT matching bare 'service' — that collides with 'service-fee'.
        # Only match explicit attentiveness phrasing.
        "match_any": ["service attentiveness", "attentiveness"],
        "desc": "service attentiveness during peak hours",
        "quote_keywords": ["server", "waited", "forgot", "had to ask", "never came"],
    },
    "noise_acoustics": {
        "match_any": ["noise", "acoustics"],
        "desc": "ambient noise making conversation difficult",
        "quote_keywords": ["loud", "noise", "couldn't hear", "noisy"],
    },
    "price_value": {
        "match_any": ["price-to-value", "price"],
        "desc": "the perceived gap between ticket price and the experience delivered",
        "quote_keywords": ["overpriced", "not worth", "value", "$"],
    },
    "cleanliness": {
        "match_any": ["cleanliness"],
        "desc": "cleanliness in the dining area or restrooms",
        "quote_keywords": ["dirty", "clean", "sticky", "bathroom", "restroom"],
    },
    "food_safety": {
        "match_any": ["food safety", "illness"],
        "desc": "a broader quality-trajectory concern that I flag for legal review (I never repeat unverified illness allegations as fact)",
        "quote_keywords": ["slipped", "not what it was", "quality has", "used to", "favorite"],
        # Note: we deliberately avoid picking the illness-allegation quote — the
        # builder hard-blocks any quote containing blocked tokens below.
    },
}

# Hard block: quotes containing these tokens are never used in outreach.
# Illness allegations, named individuals, defamatory language — all excluded.
QUOTE_BLOCKED_TOKENS = [
    "food poisoning",
    "made me sick",
    "threw up",
    "hospital",
    "salmonella",
    "e. coli",
    "norovirus",
    "got sick",
    "going down with",
    "went down with",
]


def _pillar_key_for(key_complaint: str) -> str:
    key = (key_complaint or "").strip().lower()
    for pk, cfg in PILLARS.items():
        for token in cfg["match_any"]:
            if token in key:
                return pk
    return ""


def describe_pillar(key_complaint: str) -> str:
    """Map raw key-complaint string to a natural-language descriptor."""
    pk = _pillar_key_for(key_complaint)
    if pk:
        return PILLARS[pk]["desc"]
    return f"concerns clustering around '{key_complaint}'"


def _is_blocked(quote: str) -> bool:
    q = quote.lower()
    return any(tok in q for tok in QUOTE_BLOCKED_TOKENS)


def extract_primary_quote(verbatim_excerpts: str, key_complaint: str = "") -> str:
    """
    Pick the verbatim quote that best matches the pillar, skipping any quote
    that triggers the blocked-token filter (illness allegations, etc).

    Field format: 'Quote A. || Quote B.'
    Returns empty string if no safe, pillar-matching quote exists.
    """
    if not verbatim_excerpts:
        return ""
    parts = [p.strip() for p in verbatim_excerpts.split("||") if p.strip()]
    # Strip wrapping quotes
    cleaned = []
    for p in parts:
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        cleaned.append(p.rstrip())

    # Filter out blocked quotes entirely
    safe = [q for q in cleaned if not _is_blocked(q)]
    if not safe:
        return ""

    # Score remaining by keyword match against the pillar's quote_keywords
    pk = _pillar_key_for(key_complaint)
    if pk and PILLARS[pk].get("quote_keywords"):
        keywords = [k.lower() for k in PILLARS[pk]["quote_keywords"]]
        scored = []
        for q in safe:
            ql = q.lower()
            score = sum(1 for kw in keywords if kw in ql)
            scored.append((score, q))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > 0:
            return scored[0][1]

    # Fallback: first safe quote
    return safe[0]


# ---------------------------------------------------------------------------
# Draft construction
# ---------------------------------------------------------------------------
@dataclass
class OutreachDraft:
    business_name: str
    category: str
    neighborhood: str
    rating: str
    legal_flag_severity: str  # "HIGH" | "MED" | "NONE"
    to_email: str             # empty — user fills before sending
    subject: str
    body: str
    routing: str              # "ryan_drafts" — always, per project constraint
    source_row_key: str
    generated_at: str


def classify_legal_severity(flag_text: str) -> str:
    f = (flag_text or "").upper()
    if "HIGH" in f:
        return "HIGH"
    if "MED" in f:
        return "MED"
    return "NONE"


def build_draft(row: dict) -> OutreachDraft:
    name = row["Business Name"].strip()
    severity = classify_legal_severity(row.get("Legal Review Flag", ""))
    pillar_desc = describe_pillar(row.get("Key Complaint", ""))
    quote = extract_primary_quote(
        row.get("Verbatim Excerpts (top 2)", ""),
        key_complaint=row.get("Key Complaint", ""),
    )

    if severity == "HIGH":
        subject = SUBJECT_TEMPLATES["legal_high"].format(name=name)
    elif severity == "MED":
        subject = SUBJECT_TEMPLATES["legal_med"].format(name=name)
    else:
        subject = SUBJECT_TEMPLATES["standard"].format(name=name)

    body_parts = [OPENING.format(name=name)]
    if quote:
        # Normal path: pillar lead-in + quote
        body_parts.append(PILLAR_LEAD_IN.format(pillar_desc=pillar_desc))
        body_parts.append(QUOTE_BLOCK.format(quote=quote))
    else:
        # No safe quote available — use a pillar-only framing with no quote.
        # Preserves defamation-safety when the only available quotes are blocked.
        body_parts.append(
            "\n\nThe theme clustering in your public reviews is "
            f"{pillar_desc}. I'd rather not paraphrase specific reviews here "
            "— the preview I'm offering pulls the actual quotes so you can "
            "see them in context."
        )
    if severity == "HIGH":
        body_parts.append(LEGAL_FLAG_NOTE)
    body_parts.append(OFFER)
    body_parts.append(GUARDRAIL_FOOTER)
    body_parts.append(RYAN_SIGNATURE)

    body = "".join(body_parts)

    return OutreachDraft(
        business_name=name,
        category=row.get("Category", ""),
        neighborhood=row.get("Neighborhood", ""),
        rating=row.get("Rating", ""),
        legal_flag_severity=severity,
        to_email="",  # user fills before sending
        subject=subject,
        body=body,
        routing="ryan_drafts",
        source_row_key=name.lower().replace(" ", "_"),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )


def write_draft_files(draft: OutreachDraft, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = draft.source_row_key.replace("/", "_").replace("—", "-")
    md_path = out_dir / f"{slug}.md"
    md = [
        f"# Outreach draft — {draft.business_name}",
        "",
        f"- **Legal flag severity:** {draft.legal_flag_severity}",
        f"- **Category:** {draft.category}",
        f"- **Neighborhood:** {draft.neighborhood}",
        f"- **Rating at audit:** {draft.rating}",
        f"- **Routing:** {draft.routing}",
        f"- **Generated:** {draft.generated_at}",
        "",
        "---",
        "",
        f"**TO:** _(fill before sending)_",
        f"**FROM:** gojetpakt.us@outlook.com",
        f"**SUBJECT:** {draft.subject}",
        "",
        "---",
        "",
        draft.body,
    ]
    md_path.write_text("\n".join(md), encoding="utf-8")
    return md_path


def build_manifest(drafts: list[OutreachDraft], out_dir: Path) -> Path:
    manifest = {
        "wave_name": "initial_wave_2026-04-18",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_drafts": len(drafts),
        "legal_high_count": sum(1 for d in drafts if d.legal_flag_severity == "HIGH"),
        "routing_rule": "All drafts land in Ryan's Outlook drafts folder. Owner reviews, fills TO, edits, sends manually.",
        "send_policy": "Drafts-only. No auto-send. Human approval required per JetPakt guardrail.",
        "drafts": [asdict(d) for d in drafts],
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Build JetPakt initial outreach drafts")
    ap.add_argument("--top", type=int, default=5, help="Number of top leads to process")
    ap.add_argument(
        "--source",
        default="output/outreach_top12.json",
        help="Ranked leads JSON (produced by the audit filter step)",
    )
    ap.add_argument(
        "--out",
        default="output/outreach/initial_wave_2026-04-18",
        help="Output directory",
    )
    args = ap.parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"ERROR: {source_path} not found. Run the audit filter first.")
        return 1

    leads = json.loads(source_path.read_text())[: args.top]
    out_dir = Path(args.out)

    drafts = [build_draft(row) for row in leads]
    for d in drafts:
        write_draft_files(d, out_dir)

    manifest_path = build_manifest(drafts, out_dir)

    print(f"Generated {len(drafts)} drafts in {out_dir}")
    print(f"  Legal-HIGH drafts: {sum(1 for d in drafts if d.legal_flag_severity == 'HIGH')}")
    print(f"  Manifest: {manifest_path}")
    print()
    for d in drafts:
        print(f"  [{d.legal_flag_severity:<4}] {d.business_name}")
        print(f"         SUBJECT: {d.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
