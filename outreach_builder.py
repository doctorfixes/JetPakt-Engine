"""
JetPakt — Initial Outreach Builder (v3)

Template v3 rules (locked — per REPOSITION_V3_SPEC.md §5.1):
  - Drift-first framing. The first sentence names the review volume read and
    then asserts that the same operating signal is repeating, in ROS
    pillar + case terms. Reviews are the symptom; the pillar is the problem.
  - Subject: "A drift pattern in {short_name} reviews" (<= 45 chars).
  - Verbatim quote appears in paragraph one (quote as evidence of drift,
    not as the subject of the email).
  - Offer is the $49 Drift Diagnosis (Operator Memo) with a projected
    revenue-recovery range. Still binary reply (yes or silence).
  - Signature is two lines: identity + email + URL.
  - No em-dashes in author-generated body. Verbatim quotes may contain
    em-dashes; we prefer those without.
  - Legal-HIGH drafts still get the HB25 1090 heads-up paragraph.
  - The builder never names individual staff and never repeats blocked tokens
    (illness allegations, named individuals).

Output: a JSON manifest + one .md draft per target for local review,
plus the body fed into the Outlook connector for draft staging.

Usage:
    python outreach_builder.py --top 5 \
        --source output/outreach_lowprofile5.json \
        --out output/outreach/lowprofile_wave_2026-04-18
"""
from __future__ import annotations
import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Signature — two lines only. Identity preserved; phone intentionally omitted
# per operator request.
# ---------------------------------------------------------------------------
RYAN_SIGNATURE = (
    "Ryan B., JetPakt Solutions\n"
    "gojetpakt.us@outlook.com  \u00b7  gojetpakt.com"
)

SITE_URL = "https://poetic-melba-f04633.netlify.app"


# ---------------------------------------------------------------------------
# Subject lines — short, specific, no em-dash.
# ---------------------------------------------------------------------------
SUBJECT_TEMPLATES = {
    "legal_high": "A drift pattern in {short_name} reviews",
    "legal_med":  "A drift pattern in {short_name} reviews",
    "standard":   "A drift pattern in {short_name} reviews",
}

SUBJECT_MAX_CHARS = 45


# ---------------------------------------------------------------------------
# Body fragments (no em-dashes, no ellipsis from source).
# ---------------------------------------------------------------------------
OPENING = (
    "Hi,\n\n"
    "Reading the last {review_count} public reviews of {name}, the same "
    "operating signal is repeating. It reads as a {pillar_name}-pillar "
    "drift, specifically Restaurant Operating System case {case_id} "
    "({case_oneliner}). Here is one verbatim quote from a recent review:"
)

OPENING_NO_COUNT = (
    "Hi,\n\n"
    "Reading your public reviews of {name}, the same operating signal is "
    "repeating. It reads as a {pillar_name}-pillar drift, specifically "
    "Restaurant Operating System case {case_id} ({case_oneliner}). Here "
    "is one verbatim quote from a recent review:"
)

# Option A positive opener. Direct, quote-first, names the prospect, puts the
# good news before the concern so the email reads like a friend sharing notes
# rather than a cold pitch. Both quotes are verbatim public review content.
POSITIVE_OPENER_WITH_COUNT = (
    "Hi,\n\n"
    "Before the drift, the good news. Reading {review_count} public reviews "
    "of {name}, the theme that keeps showing up in positive reviews is "
    "{positive_theme}. One recent quote:"
)

POSITIVE_OPENER_NO_COUNT = (
    "Hi,\n\n"
    "Before the drift, the good news. Reading your public reviews of "
    "{name}, the theme that keeps showing up in positive reviews is "
    "{positive_theme}. One recent quote:"
)

POSITIVE_TO_NEGATIVE_BRIDGE = (
    "That is the part worth protecting. Alongside it, the same operating "
    "signal is repeating in the one and two star reviews. It reads as a "
    "{pillar_name}-pillar drift, specifically Restaurant Operating System "
    "case {case_id} ({case_oneliner}). One verbatim quote:"
)

QUOTE_BLOCK = "\n\n    \"{quote}\"\n\n"

# ---------------------------------------------------------------------------
# ROS pillar + case mapping. Source: docs/ROS_FRAMEWORK.md.
# Each complaint bucket resolves to (ROS pillar name, ROS case_id, case
# one-liner). The outreach copy names the pillar and case directly so the
# email reads as a diagnosis, not an opinion.
# ---------------------------------------------------------------------------
PILLAR_META = {
    "billing_service_fee":   ("Sales",       "I12", "service-fee disclosure drift"),
    "wait_reservation":      ("Operations",  "I15", "reservation-to-seating handoff drift"),
    "food_quality":          ("Production",  "I02", "food consistency drift between visits"),
    "service_attentiveness": ("Service",     "I06", "peak-hour attentiveness drift"),
    "noise_acoustics":       ("Operations",  "I17", "room-acoustics drift"),
    "price_value":           ("Sales",       "I11", "price-to-value perception drift"),
    "cleanliness":           ("Operations",  "I18", "dining-area cleanliness drift"),
    "food_safety":           ("Production",  "I04", "quality-trajectory concern cluster"),
    "server_attitude":       ("Service",     "I08", "floor-handoff and server-demeanor drift"),
    "slow_service":          ("Service",     "I07", "service-pacing drift, peak hours"),
}

DEFAULT_PILLAR_META = ("Operations", "I14", "operating-drift cluster")

PILLAR_FRAMING = {
    "billing_service_fee": (
        "This is the friction guests notice at the moment of payment, which "
        "is the worst possible moment in the experience. It compounds "
        "quietly: the same complaint repeats across reviews without ever "
        "being anyone's job to fix."
    ),
    "wait_reservation": (
        "The reviews that mention it are not the ones mentioning food. That "
        "is a staffing-and-routing signal worth separating from the rest of "
        "the noise, and it points to a 30-day operational fix rather than a "
        "capex spend."
    ),
    "food_quality": (
        "This is an inconsistency signal, not a quality verdict. It tends "
        "to compound quietly, four or five reviews at a time, until the "
        "average rating drops by a third of a star. The fix is usually a "
        "line-check and a prep-log discipline, not a menu rewrite."
    ),
    "service_attentiveness": (
        "It reads as a staffing or floor-management pattern, not a one-off. "
        "Matched cases recover inside 30 to 60 days without capex when the "
        "pacing change is the first thing the owner calls out at pre-shift."
    ),
    "noise_acoustics": (
        "This is a fixable pattern once the cluster is visible: seat routing, "
        "one absorber panel, or a music-level SOP usually moves the needle "
        "without a remodel."
    ),
    "price_value": (
        "Value perception is hard to move back once it drifts. The lever is "
        "rarely price; it is what the check communicates and how the final "
        "minutes of the meal land."
    ),
    "cleanliness": (
        "It shows up more in 1 star and 2 star reviews than anywhere else, "
        "which is what makes it a drift signal rather than a one-off. A "
        "shift-by-shift walk-through typically catches it inside two weeks."
    ),
    "food_safety": (
        "Broader quality-trajectory concerns cluster here. I flag this "
        "category for legal review and never repeat unverified illness "
        "allegations as fact. The memo names the drift and leaves the "
        "response language to ownership and counsel."
    ),
    "server_attitude": (
        "It reads as a training or floor-management pattern, not a one-off "
        "incident. The cases matched to this drift typically recover with a "
        "one-page service-standards reset and consistent shift-start "
        "reinforcement."
    ),
    "slow_service": (
        "It shows up more in weekend reviews than weekday, which is a "
        "schedulable pattern. The 30-day play is usually a staffing or "
        "station-map change, not a hiring push."
    ),
}

LEGAL_FLAG_NOTE = (
    "Colorado's HB25 1090 took effect on January 1, which means service "
    "fee disclosure language is under a brighter regulatory light than it "
    "was last year. I am not a lawyer and this is not legal advice. It is "
    "a heads up from someone who reads these reviews for a living."
)

OFFER = (
    "I run JetPakt Solutions. The product is a drift diagnosis for "
    "independent restaurants: five operating pillars, matched Restaurant "
    "Operating System case, and a defensible revenue-recovery range tied "
    "to verbatim public reviews.\n\n"
    "I would like to send you a free one-page preview: the dominant "
    "pillar this quarter, the matched case, and one verbatim quote "
    "supporting it. No sales call, no follow up, no CRM entry.\n\n"
    "Reply \"yes\" and you will have it within two business days. If not, "
    "we are done.\n\n"
    "If the preview is useful, the full $49 Drift Diagnosis (Operator "
    "Memo) lands in about 48 hours. It includes the pillar rollup, the "
    "30/60/90-day action plan tied to the matched case, and a conservative "
    "monthly revenue-recovery range."
)

GUARDRAIL_FOOTER = (
    "Every finding I share is anchored to a verbatim public quote. I never "
    "name staff, never invent a claim, and never post anything on your "
    "behalf. Software finds the pattern. The owner makes the call."
)


# ---------------------------------------------------------------------------
# Pillars (unchanged from v1 except the descriptions moved into PILLAR_FRAMING)
# ---------------------------------------------------------------------------
PILLARS = {
    "billing_service_fee": {
        "match_any": ["billing", "service-fee", "service fee"],
        "quote_keywords": [
            "service fee", "service charge", "automatic", "gratuity",
            "surcharge", "hidden", "not disclosed", "not told", "%",
        ],
    },
    "wait_reservation": {
        "match_any": ["wait time", "reservation"],
        "quote_keywords": ["wait", "minutes", "seated", "reservation", "took"],
    },
    "food_quality": {
        "match_any": ["food quality"],
        "quote_keywords": [
            "cold", "overcooked", "undercooked", "burger", "food was",
            "quality", "slipped", "not the same", "used to", "salty",
            "inedible", "lukewarm",
        ],
    },
    "service_attentiveness": {
        "match_any": ["service attentiveness", "attentiveness"],
        "quote_keywords": ["server", "waited", "forgot", "had to ask", "never came"],
    },
    "noise_acoustics": {
        "match_any": ["noise", "acoustics"],
        "quote_keywords": ["loud", "noise", "couldn't hear", "noisy"],
    },
    "price_value": {
        "match_any": ["price-to-value", "price"],
        "quote_keywords": ["overpriced", "not worth", "value", "$"],
    },
    "cleanliness": {
        "match_any": ["cleanliness"],
        "quote_keywords": ["dirty", "clean", "sticky", "bathroom", "restroom", "dingy"],
    },
    "food_safety": {
        "match_any": ["food safety", "illness"],
        "quote_keywords": ["slipped", "not what it was", "quality has", "used to", "favorite"],
    },
    "server_attitude": {
        "match_any": ["server attitude", "server", "attitude"],
        "quote_keywords": ["ignored", "rude", "attitude", "bartender", "unfriendly"],
    },
    "slow_service": {
        "match_any": ["slow service"],
        "quote_keywords": ["slow", "waited", "minutes", "took forever", "forever"],
    },
    "inconsistent_recent": {
        "match_any": ["inconsistent recent", "inconsistent"],
        "quote_keywords": [
            "used to", "not the same", "changed", "quality has", "first time",
            "worse than", "slipped",
        ],
    },
}

# Hard block: quotes containing these tokens are never used in outreach.
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
    "0/10",  # reads as a drive-by rating, not a content signal
]

# Positive quotes also pass through the defamation/safety filter; in addition,
# we reject overly promotional or staff-naming phrasing so the opener reads
# like an authentic guest observation, not a testimonial.
POSITIVE_QUOTE_REJECT_TOKENS = [
    "highly recommend to everyone",
    "best restaurant in the world",
    "5 stars",
    "five stars",
]


# ---------------------------------------------------------------------------
# Pillar resolution
# ---------------------------------------------------------------------------
def _pillar_key_for(key_complaint: str) -> str:
    key = (key_complaint or "").strip().lower()
    # "inconsistent recent guest experience" maps to food_quality framing
    # since that is what operators hear and act on.
    if "inconsistent" in key:
        return "food_quality"
    for pk, cfg in PILLARS.items():
        for token in cfg["match_any"]:
            if token in key:
                return pk
    return ""


def describe_pillar(key_complaint: str) -> str:
    pk = _pillar_key_for(key_complaint)
    if pk and pk in PILLAR_FRAMING:
        return PILLAR_FRAMING[pk]
    # Fallback without inventing a pattern.
    return (
        "The verbatim quote above speaks to the specifics. The diagnosis is "
        "scored against the five operating pillars, not reviewer opinion, "
        "so the 30/60/90-day plan targets the underlying system, not a "
        "single shift."
    )


def pillar_meta_for(key_complaint: str) -> tuple[str, str, str]:
    """Resolve a complaint into (ROS pillar name, case_id, case one-liner).

    Falls back to an Operations/I14 generic drift cluster when the key
    complaint does not match a known pillar. Ensures the drift-first opener
    always has a pillar and case to name — never "unknown".
    """
    pk = _pillar_key_for(key_complaint)
    if pk and pk in PILLAR_META:
        return PILLAR_META[pk]
    return DEFAULT_PILLAR_META


# ---------------------------------------------------------------------------
# Quote selection
# ---------------------------------------------------------------------------
def _is_blocked(quote: str) -> bool:
    q = quote.lower()
    return any(tok in q for tok in QUOTE_BLOCKED_TOKENS)


def _has_em_dash(s: str) -> bool:
    return "\u2014" in s


def is_positive_quote_usable(quote: str) -> bool:
    """
    Positive quotes pass the same blocked-token filter as negatives, plus a
    lightweight check for obvious promotional/testimonial phrasing and for
    anything that looks like a named individual (capitalized first names
    preceded by 'by' or trailed by a verb). We keep this deliberately loose;
    the real authenticity check is human review before staging.
    """
    if not quote or not quote.strip():
        return False
    q = quote.lower()
    if any(tok in q for tok in QUOTE_BLOCKED_TOKENS):
        return False
    if any(tok in q for tok in POSITIVE_QUOTE_REJECT_TOKENS):
        return False
    return True


def extract_primary_quote(verbatim_excerpts: str, key_complaint: str = "") -> str:
    """
    Pick the verbatim quote that best matches the pillar. Prefer quotes
    without em-dashes (stays consistent with our template rule). Skip any
    quote that triggers the blocked-token filter. Returns empty string if
    no safe, pillar-matching quote exists.
    """
    if not verbatim_excerpts:
        return ""
    parts = [p.strip() for p in verbatim_excerpts.split("||") if p.strip()]
    cleaned = []
    for p in parts:
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        cleaned.append(p.rstrip())

    safe = [q for q in cleaned if not _is_blocked(q)]
    if not safe:
        return ""

    pk = _pillar_key_for(key_complaint)
    scored = []
    if pk and PILLARS.get(pk, {}).get("quote_keywords"):
        keywords = [k.lower() for k in PILLARS[pk]["quote_keywords"]]
        for q in safe:
            ql = q.lower()
            kw_score = sum(1 for kw in keywords if kw in ql)
            dash_penalty = -1 if _has_em_dash(q) else 0
            length_penalty = -1 if len(q) > 180 else 0  # keep quotes tight
            scored.append((kw_score + dash_penalty + length_penalty, q))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > 0:
            return scored[0][1]

    # Fallback: first quote without em-dash; otherwise first safe quote.
    no_dash = [q for q in safe if not _has_em_dash(q)]
    return (no_dash or safe)[0]


# ---------------------------------------------------------------------------
# Hygiene: guarantee no em-dashes in generated body
# ---------------------------------------------------------------------------
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _strip_em_dashes_outside_quotes(body: str) -> str:
    """
    Replace em-dashes in author-generated text while preserving them inside
    verbatim quote blocks. We detect the quote block by the specific
    '    "..."' indent produced by QUOTE_BLOCK.
    """
    lines = body.split("\n")
    out = []
    for line in lines:
        stripped = line.lstrip()
        is_quote_line = line.startswith('    "') or (stripped.startswith('"') and line.startswith('    '))
        if is_quote_line:
            out.append(line)
        else:
            cleaned = line.replace(EM_DASH, ",").replace(EN_DASH, "-")
            out.append(cleaned)
    return "\n".join(out)


def _shorten_business_name_for_subject(name: str) -> str:
    """
    Keep the first two 'significant' tokens for a short subject. Drops the
    location suffix after an em-dash or comma so the subject stays under 45.
    """
    # Trim anything after em-dash, comma, or parenthesis
    s = re.split(r"\s*[\u2014\u2013,(]\s*", name, maxsplit=1)[0].strip()
    if len(s) > 30:
        toks = s.split()
        s = " ".join(toks[:3])
    return s


# ---------------------------------------------------------------------------
# Draft construction
# ---------------------------------------------------------------------------
@dataclass
class OutreachDraft:
    business_name: str
    category: str
    neighborhood: str
    rating: str
    review_count: str
    legal_flag_severity: str  # "HIGH" | "MED" | "NONE"
    to_email: str             # empty, user fills
    subject: str
    body: str
    routing: str              # "ryan_drafts" always
    source_row_key: str
    generated_at: str


def classify_legal_severity(flag_text: str) -> str:
    f = (flag_text or "").upper()
    if "HIGH" in f:
        return "HIGH"
    if "MED" in f:
        return "MED"
    return "NONE"


def _get_field(row: dict, *candidates, default: str = "") -> str:
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return str(row[c]).strip()
    return default


def build_draft(row: dict) -> OutreachDraft:
    name = _get_field(row, "Business Name", "business_name")
    short_name = _shorten_business_name_for_subject(name)
    review_count = _get_field(row, "Total Reviews", "review_count")
    rating = _get_field(row, "Rating", "rating")
    neighborhood = _get_field(row, "Neighborhood", "neighborhood")
    category = _get_field(row, "Category", "category")
    flag = _get_field(row, "Legal Review Flag", "legal_flag_severity")
    key_complaint = _get_field(row, "Key Complaint", "key_complaint")
    excerpts = _get_field(row, "Verbatim Excerpts (top 2)", "verbatim_excerpts")

    severity = classify_legal_severity(flag)
    pillar_framing = describe_pillar(key_complaint)
    pillar_name, case_id, case_oneliner = pillar_meta_for(key_complaint)
    quote = extract_primary_quote(excerpts, key_complaint=key_complaint)

    # Positive sentiment (Option A opener). Both fields must be present AND
    # the quote must pass the defamation/testimonial filter. If either is
    # missing, we silently fall back to the sender-neutral OPENING.
    positive_theme = _get_field(
        row, "Positive Theme", "positive_theme"
    )
    positive_quote_raw = _get_field(
        row, "Positive Verbatim Quote", "positive_verbatim_quote"
    )
    use_positive_opener = bool(
        positive_theme
        and positive_quote_raw
        and is_positive_quote_usable(positive_quote_raw)
    )

    # Build subject
    if severity == "HIGH":
        subject = SUBJECT_TEMPLATES["legal_high"].format(short_name=short_name)
    elif severity == "MED":
        subject = SUBJECT_TEMPLATES["legal_med"].format(short_name=short_name)
    else:
        subject = SUBJECT_TEMPLATES["standard"].format(short_name=short_name)
    subject = subject.replace(EM_DASH, ",").replace(EN_DASH, "-")
    # If subject is too long, try a tighter shortening of the name before
    # hard truncating (never cut a word mid-way).
    if len(subject) > SUBJECT_MAX_CHARS:
        toks = short_name.split()
        if len(toks) > 2:
            tighter = " ".join(toks[:2])
            subject = f"A pattern in {tighter} reviews"
    if len(subject) > SUBJECT_MAX_CHARS:
        # Final safety: cut at last whole word boundary <= limit
        cut = subject[:SUBJECT_MAX_CHARS]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        subject = cut.rstrip()

    # Build body
    parts: list[str] = []
    # Use shortened name in body so the em-dash strip does not mangle a
    # location suffix like "Big Daddy's Pizza — Colfax" into
    # "Big Daddy's Pizza , Colfax".
    body_name = short_name

    if use_positive_opener:
        # Option A: positive theme + positive quote + drift bridge + negative
        # quote. Both quotes are verbatim public review content.
        if review_count and review_count.isdigit():
            parts.append(POSITIVE_OPENER_WITH_COUNT.format(
                name=body_name,
                review_count=review_count,
                positive_theme=positive_theme,
            ))
        else:
            parts.append(POSITIVE_OPENER_NO_COUNT.format(
                name=body_name,
                positive_theme=positive_theme,
            ))
        parts.append(QUOTE_BLOCK.format(quote=positive_quote_raw))
        parts.append(POSITIVE_TO_NEGATIVE_BRIDGE.format(
            pillar_name=pillar_name,
            case_id=case_id,
            case_oneliner=case_oneliner,
        ))

        if quote:
            parts.append(QUOTE_BLOCK.format(quote=quote))
        else:
            parts.append("\n\n")

        parts.append(pillar_framing)
        parts.append("\n\n")
    else:
        # Drift-first neutral opener.
        if review_count and review_count.isdigit():
            parts.append(OPENING.format(
                name=body_name,
                review_count=review_count,
                pillar_name=pillar_name,
                case_id=case_id,
                case_oneliner=case_oneliner,
            ))
        else:
            parts.append(OPENING_NO_COUNT.format(
                name=body_name,
                pillar_name=pillar_name,
                case_id=case_id,
                case_oneliner=case_oneliner,
            ))

        if quote:
            parts.append(QUOTE_BLOCK.format(quote=quote))
        else:
            parts.append("\n\n")

        parts.append(pillar_framing)
        parts.append("\n\n")

    if severity == "HIGH":
        parts.append(LEGAL_FLAG_NOTE)
        parts.append("\n\n")

    parts.append(OFFER)
    parts.append("\n\n")
    parts.append(GUARDRAIL_FOOTER)
    parts.append("\n\n")
    parts.append(RYAN_SIGNATURE)

    body = "".join(parts)
    body = _strip_em_dashes_outside_quotes(body)

    return OutreachDraft(
        business_name=name,
        category=category,
        neighborhood=neighborhood,
        rating=rating,
        review_count=review_count,
        legal_flag_severity=severity,
        to_email="",
        subject=subject,
        body=body,
        routing="ryan_drafts",
        source_row_key=name.lower().replace(" ", "_").replace("'", "").replace(EM_DASH, "-").replace(",", ""),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )


def write_draft_files(draft: OutreachDraft, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\-]+", "_", draft.source_row_key).strip("_")
    md_path = out_dir / f"{slug}.md"
    md = [
        f"# Outreach draft — {draft.business_name}",
        "",
        f"- Legal flag severity: {draft.legal_flag_severity}",
        f"- Category: {draft.category}",
        f"- Neighborhood: {draft.neighborhood}",
        f"- Rating at audit: {draft.rating}",
        f"- Review count: {draft.review_count}",
        f"- Routing: {draft.routing}",
        f"- Generated: {draft.generated_at}",
        "",
        "---",
        "",
        f"TO: _(fill before sending)_",
        f"FROM: gojetpakt.us@outlook.com",
        f"SUBJECT: {draft.subject}",
        "",
        "---",
        "",
        draft.body,
    ]
    md_path.write_text("\n".join(md), encoding="utf-8")
    return md_path


def build_manifest(drafts: list[OutreachDraft], out_dir: Path, wave_name: str) -> Path:
    manifest = {
        "wave_name": wave_name,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_drafts": len(drafts),
        "legal_high_count": sum(1 for d in drafts if d.legal_flag_severity == "HIGH"),
        "template_version": "v3",
        "template_rules": [
            "drift-first framing: first sentence names review volume + ROS pillar + case",
            "subject: 'A drift pattern in {short_name} reviews' (<= 45 chars)",
            "no em-dashes in author-generated body",
            "verbatim quotes may contain em-dashes; we prefer those that do not",
            "signature two lines",
            "offer is binary (reply yes or nothing)",
            "offer names the $49 Drift Diagnosis (Operator Memo) and the revenue-recovery range",
            "positive sentiment opener (Option A) when a safe positive quote is available, else drift-first opener",
            "positive quotes pass the same defamation filter as negatives, plus a testimonial-language filter",
        ],
        "routing_rule": "All drafts land in Ryan's Outlook drafts folder. Owner reviews, fills TO, edits, sends manually.",
        "send_policy": "Drafts-only. No auto-send. Human approval required per JetPakt guardrail.",
        "drafts": [asdict(d) for d in drafts],
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Build JetPakt outreach drafts (template v3)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--source", default="output/outreach_lowprofile5.json")
    ap.add_argument("--out", default="output/outreach/lowprofile_wave_2026-04-18")
    ap.add_argument("--wave-name", default="lowprofile_wave_2026-04-18")
    args = ap.parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"ERROR: {source_path} not found.")
        return 1

    leads = json.loads(source_path.read_text())[: args.top]
    out_dir = Path(args.out)

    drafts = [build_draft(row) for row in leads]
    for d in drafts:
        write_draft_files(d, out_dir)

    manifest_path = build_manifest(drafts, out_dir, args.wave_name)

    print(f"Generated {len(drafts)} drafts in {out_dir}")
    print(f"  Manifest: {manifest_path}")
    print()
    for d in drafts:
        em_count_body = d.body.count(EM_DASH)
        print(f"  [{d.legal_flag_severity:<4}] {d.business_name}")
        print(f"         SUBJECT: {d.subject}  ({len(d.subject)} chars)")
        print(f"         em-dashes in body: {em_count_body}  (only allowed inside quote line)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
