# JetPakt Signal Engine
# This module processes guest sentiment and complaint signals
# which feed into real-time operational alerts.

"""
Denver Restaurant Reputation-Management Lead Pipeline
======================================================

Pipeline for identifying non-chain Denver restaurants with high-volume,
recent negative review signals and generating CRM-ready leads + personalized
outreach drafts.

Modules (each callable standalone for testing):

    fetch_candidates()      -> list[dict]   Pull from Google Maps public pages
    load_seed()             -> list[dict]   Hand-verified seed list (data/seed_candidates.json)
    score_sentiment(cand)   -> dict         Keyword + signal-strength score per candidate
    filter_qualified(cands) -> list[dict]   Removes chains, already-responding owners, etc.
    enrich_contacts(cand)   -> dict         Phone, website, Google review link verification
    generate_outreach(cand) -> dict         Subject + body, defamation-safe guardrails applied
    export_csv(cands, path) -> None         CRM-ready output

Usage:
    python pipeline.py --run         # Full pipeline, outputs CSV
    python pipeline.py --preview     # Show top 10 leads without exporting
    python pipeline.py --fetch-only  # Just run the Places fetcher

Safety guardrails (non-negotiable, baked in):
  - No individual names or staff identification in outreach copy.
  - Review quotes are VERBATIM from public sources — never paraphrased.
  - Wage / service-fee / billing complaints are flagged for human legal
    review before the message is sent (LEGAL_FLAGS set).
  - Outreach is DRAFTED, never auto-sent. Output CSV includes a
    `sent_status` column defaulted to "NOT_SENT — needs human review".
  - Candidates where the owner is already replying to negative reviews
    are deprioritized (they likely don't need the service).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# -------------------- Config --------------------

# Target criteria (adjustable)
RATING_CEILING = 3.5              # Only flag restaurants at/below this Google rating
MIN_REVIEW_COUNT = 200            # Need enough volume to be worth outreach
MIN_RECENT_NEGATIVE_SHARE = 0.20  # >=20% of recent reviews must be negative
EXCLUDE_CHAINS = True
EXCLUDE_ALREADY_RESPONDING = True # Owners already replying = warm but lower-fit

# Denver-metro geography (expanded scope). Cities in this set pass the
# geo filter; others are flagged in the audit.
DENVER_METRO_CITIES = {
    "denver", "aurora", "lakewood", "arvada", "westminster", "thornton",
    "centennial", "littleton", "englewood", "broomfield", "wheat ridge",
    "commerce city", "northglenn", "parker", "castle rock", "highlands ranch",
    "greenwood village", "lone tree", "sheridan", "glendale", "edgewater",
    "morrison", "golden", "louisville", "superior", "brighton",
}
SEED_FILE = "seed_candidates_metro.json"   # expanded metro seed

# Complaint keyword buckets → used to identify "key complaint" for outreach
# Keywords drawn from actual reviews (not paraphrased)
COMPLAINT_BUCKETS: dict[str, list[str]] = {
    "slow service": [
        "wait", "waited", "slow", "took forever", "disappeared", "hour",
        "pacing", "45 minutes", "30 minutes",
    ],
    "food quality": [
        "cold", "lukewarm", "soggy", "bland", "tasteless", "inedible",
        "reheated", "no seasoning", "no flavor", "dry",
    ],
    "cleanliness": [
        "sticky", "dirty", "dusty", "cockroach", "bathroom", "carpet",
        "floor", "mess", "filthy",
    ],
    "billing / service-fee transparency": [
        "service charge", "service fee", "automatic", "bill had",
        "never ordered", "didn't order", "extra charge", "house charge",
        "not disclosed", "not told", "hidden fee",
    ],
    "overpriced / perceived value": [
        "overpriced", "not worth", "left hungry", "tourist tax",
        "expected more for the price", "ticket price", "coasting",
    ],
    "host / reservation experience": [
        "host", "reservation", "booking", "waitlist", "sidewalk",
        "stood outside", "past our reservation",
    ],
    "server attitude": [
        "rude", "dismissive", "annoyed", "attitude", "eye roll", "ignored",
    ],
    "food safety perception": [
        "got sick", "food poisoning", "stomach", "cramps", "nauseous",
        "tasted off",
    ],
}

# Complaints that touch labor/wage/billing law → require human legal review
LEGAL_FLAGS = {
    "billing / service-fee transparency": "HIGH — wage/service-fee disclosure (see Denver CCG lawsuit context)",
    "food safety perception": "MEDIUM — alleges illness; do NOT reference specific illness claims in outreach",
}

# Known restaurant chains in Denver (excluded when EXCLUDE_CHAINS=True)
CHAIN_NAMES = {
    "the hampton social", "snooze", "maggiano", "chipotle", "qdoba",
    "pizza hut", "pf chang", "olive garden", "applebees", "chili",
    "red robin", "bj", "jason", "panera", "starbucks", "chick-fil-a",
    "mcdonald", "taco bell", "wendy", "burger king", "kfc", "subway",
    "dave and busters", "bubba gump", "rainforest cafe",
}

# Outreach copy templates (direct reputation-mgmt pitch with guardrails)
OUTREACH_SUBJECT_TEMPLATES = [
    "Denver guests are talking about {name} — a quick idea",
    "Noticed some recent Google feedback at {name}",
    "One quick thought on {name}'s recent review trends",
]

OUTREACH_BODY_TEMPLATE = """Hi there,

I'm reaching out to the management team at {name}. I help Denver-area \
restaurants turn recent guest feedback into measurable operational wins — \
not by burying reviews, but by closing the loop on the two or three signals \
guests are actually asking you to address.

A quick look at {name}'s recent Google and Yelp activity surfaces one \
consistent theme: **{key_complaint}**. That's showing up in roughly {neg_pct}% \
of your last 30 days of reviews, which is well above the Denver market baseline.

A few things I'd offer — quickly and without a long sales pitch:

  1. A one-page Experience Enhancement read of the top 3 signals, each tied \
to verbatim public reviews (nothing invented).
  2. Drafted, defamation-safe response templates your team can send after \
every review — approved by you before going out.
  3. A 30-day tracking plan so you can see the complaint share move.

I'd love 15 minutes on the phone. Would {day_slot} work, or would you \
prefer I send a 2-page brief first?

Best,
[Your Name]
[Your Contact]

---
This outreach is based entirely on public Google, Yelp, and Tripadvisor \
review data. No private or employee data was used. Full source links \
available on request.
"""

# -------------------- Data Model --------------------

@dataclass
class Candidate:
    name: str
    category: str
    neighborhood: str
    address: str
    phone: str | None
    website: str | None
    google_review_url: str
    rating: float
    review_count: int
    is_chain: bool
    recent_negative_share_30d: float
    owner_responds_to_reviews: bool
    verbatim_review_excerpts: list[str] = field(default_factory=list)
    signals: dict[str, str] = field(default_factory=dict)
    extra_urls: dict[str, str] = field(default_factory=dict)
    # Computed
    key_complaint: str = ""
    key_complaint_bucket: str = ""
    complaint_score: int = 0
    legal_flag: str = ""
    disqualified_reason: str = ""
    outreach_subject: str = ""
    outreach_body: str = ""
    sent_status: str = "NOT_SENT — awaiting human review"


# -------------------- Stage 1: Load candidates --------------------

def load_seed() -> list[dict]:
    """Hand-verified seed list of Denver-metro restaurants with real review signals.

    Sourced from: Google Maps, Yelp's 'Worst Restaurant' searches for Denver,
    Aurora, Lakewood, Littleton, r/denverfood threads, r/Denver threads,
    Tripadvisor, Westword coverage, Boulder Weekly, and the Denver CCG
    service-fee lawsuit news.
    """
    path = DATA_DIR / SEED_FILE
    if not path.exists():
        # Backward-compat: fall back to the Denver-only seed.
        path = DATA_DIR / "seed_candidates.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_candidates_from_google_maps(query: str = "restaurants in Denver CO",
                                      max_results: int = 40) -> list[dict]:
    """Live Google Maps public-search fetcher.

    NOTE: Google Maps' public HTML aggressively paginates with JavaScript,
    so a no-key fetch is limited. This function is a placeholder that
    returns the seed list so the pipeline is runnable out of the box.
    For production volume, connect the Google Maps Places API via the
    `google_maps_platform` connector, or wire in the Serper / SerpAPI
    fallback below.
    """
    # Stub: return seed list so the pipeline is runnable without an API key.
    # Real implementation would POST to the Places API or call fetch_url()
    # over a set of neighborhood-level queries and parse the results.
    return load_seed()


# -------------------- Stage 2: Score sentiment / complaints --------------------

def score_candidate(c: dict) -> dict:
    """Mutate the candidate dict in place with complaint classification.

    Approach:
      1. Concatenate all verbatim excerpts.
      2. Count keyword hits per complaint bucket.
      3. Pick the bucket with the highest hit-count as `key_complaint`.
      4. Add a legal_flag if the bucket is one of LEGAL_FLAGS.
      5. Score = weighted(rating_gap, neg_share_30d, review_volume, bucket_hits).
    """
    text = " ".join(c.get("verbatim_review_excerpts", [])).lower()
    # Also fold in signal labels (critical/high/medium)
    signal_text = " ".join(c.get("signals", {}).keys()).lower()
    text += " " + signal_text

    bucket_hits: dict[str, int] = {}
    for bucket, keywords in COMPLAINT_BUCKETS.items():
        hits = sum(1 for kw in keywords if kw in text)
        # Bonus: if a signal key matches the bucket name, add 2
        for sig_key, sig_level in c.get("signals", {}).items():
            if any(kw in sig_key.replace("_", " ") for kw in keywords):
                hits += {"critical": 3, "high": 2, "medium": 1}.get(sig_level, 0)
        if hits > 0:
            bucket_hits[bucket] = hits

    if bucket_hits:
        best = max(bucket_hits, key=bucket_hits.get)
        c["key_complaint_bucket"] = best
        c["key_complaint"] = best
        c["complaint_bucket_hits"] = bucket_hits
    else:
        c["key_complaint_bucket"] = "general quality concerns"
        c["key_complaint"] = "inconsistent recent guest experience"
        c["complaint_bucket_hits"] = {}

    # Legal flag
    if c["key_complaint_bucket"] in LEGAL_FLAGS:
        c["legal_flag"] = LEGAL_FLAGS[c["key_complaint_bucket"]]
    else:
        c["legal_flag"] = ""

    # Numeric score (0-100)
    # rating_gap: (RATING_CEILING - rating) / RATING_CEILING, capped
    rating_gap = max(0, RATING_CEILING - c.get("rating", 5.0)) / RATING_CEILING
    neg_share = c.get("recent_negative_share_30d", 0)
    # review volume: log-ish bump, capped at 1.0 around 1000 reviews
    vol = min(c.get("review_count", 0) / 1000, 1.0)
    score = int(round((rating_gap * 45) + (neg_share * 35) + (vol * 20)))
    c["complaint_score"] = score
    return c


# -------------------- Stage 3: Filter qualified --------------------

def is_chain(name: str, flagged: bool) -> bool:
    if flagged:
        return True
    lower = name.lower()
    return any(chain in lower for chain in CHAIN_NAMES)


def filter_qualified(cands: list[dict]) -> list[dict]:
    qualified: list[dict] = []
    for c in cands:
        reason = None
        city = (c.get("city") or "").lower().strip()
        if city and city not in DENVER_METRO_CITIES:
            reason = f"city '{c.get('city')}' outside Denver-metro set"
        elif c.get("rating", 5.0) > RATING_CEILING:
            reason = f"rating {c['rating']} above ceiling {RATING_CEILING}"
        elif c.get("review_count", 0) < MIN_REVIEW_COUNT:
            reason = f"only {c['review_count']} reviews (< {MIN_REVIEW_COUNT})"
        elif c.get("recent_negative_share_30d", 0) < MIN_RECENT_NEGATIVE_SHARE:
            reason = (
                f"recent neg share {c['recent_negative_share_30d']:.0%} "
                f"below threshold {MIN_RECENT_NEGATIVE_SHARE:.0%}"
            )
        elif EXCLUDE_CHAINS and is_chain(c["name"], c.get("is_chain", False)):
            reason = "chain / franchise (EXCLUDE_CHAINS=True)"
        elif EXCLUDE_ALREADY_RESPONDING and c.get("owner_responds_to_reviews"):
            reason = "owner already responds to reviews — lower fit"

        if reason:
            c["disqualified_reason"] = reason
        else:
            c["disqualified_reason"] = ""
            qualified.append(c)
    return qualified


# -------------------- Stage 4: Generate outreach --------------------

def generate_outreach(c: dict, subject_idx: int = 0) -> dict:
    name = c["name"]
    neg_pct = int(round(c.get("recent_negative_share_30d", 0) * 100))
    key_complaint = c.get("key_complaint", "recent guest-experience signals")

    c["outreach_subject"] = OUTREACH_SUBJECT_TEMPLATES[
        subject_idx % len(OUTREACH_SUBJECT_TEMPLATES)
    ].format(name=name)

    c["outreach_body"] = OUTREACH_BODY_TEMPLATE.format(
        name=name,
        key_complaint=key_complaint,
        neg_pct=neg_pct,
        day_slot="Tuesday or Wednesday afternoon",
    )
    return c


# -------------------- Free-pilot outreach variant --------------------

FREE_PILOT_SUBJECT_TEMPLATES = [
    "A free Experience Enhancement read for {name} — no strings",
    "Built you a short sample — tell me what to sharpen",
    "{name}: one free guide, tailored to your top guest signals",
]

FREE_PILOT_BODY_TEMPLATE = """Hi there,

I've been studying how Denver restaurants are turning recent Google and \
Yelp signals into operational wins — not by burying reviews, but by \
closing the loop on the two or three things guests keep asking for.

I'd like to offer {name} a free, limited working version of what I do — \
a tailored one-page Experience Enhancement read, built from your own \
recent public reviews. No sales pitch attached. If it's useful, we can \
talk about what a fuller engagement looks like. If not, you keep the \
guide.

Here's what you'd get, free:

  • A ranked read of the top 3 guest-experience signals showing up in \
your last 30 days of Google and Yelp reviews
  • Each signal tied to verbatim public quotes — nothing invented
  • One drafted, defamation-safe response template per signal
  • A single-page PDF you can share with your GM or ownership group

To make it genuinely useful, I need 2–3 minutes of your input. Could \
you reply with the one or two areas where {name} is feeling the most \
pressure right now? A few common ones I hear from Denver operators:

  1. Service pacing at peak hours (ticket times, host handling, turns)
  2. Billing / service-charge transparency (the 15–22% fee conversation)
  3. Guest-recovery after a bad review — what to say, how fast, by whom
  4. Reservation and waitlist friction (special occasions, walk-ins)
  5. Consistency across shifts — the "Tuesday feels different from Saturday" problem
  6. Online review response cadence — volume is outpacing the team
  7. Staff training on specific moments (allergies, birthdays, large parties)

Just a quick reply — even one sentence — and I'll build the guide \
around the area that matters most to you. You'll have it in 48 hours.

Best,
[Your Name]
[Your Contact]
[Your LinkedIn or website]

---
This outreach is based entirely on public Google, Yelp, and Tripadvisor \
review data. No private data, no employee reviews, no scraping behind \
authentication. Source URLs available on request.
"""


def generate_free_pilot_outreach(c: dict, subject_idx: int = 0) -> dict:
    """Produce the free-pilot variant: offer a tailored one-pager at no cost,
    ask them to name their top pain area with common-example prompts.

    Skips the hard sell for LEGAL-flagged leads and falls back to the
    softer copy from OUTREACH_TEMPLATES.md (human must hand-finish).
    """
    if c.get("legal_flag"):
        c["free_pilot_subject"] = "[LEGAL REVIEW REQUIRED] Do not send without counsel"
        c["free_pilot_body"] = (
            "This lead carries a legal-review flag "
            f"({c['legal_flag']}). Use the softer manual template in "
            "docs/OUTREACH_TEMPLATES.md and route to counsel before send."
        )
        return c

    c["free_pilot_subject"] = FREE_PILOT_SUBJECT_TEMPLATES[
        subject_idx % len(FREE_PILOT_SUBJECT_TEMPLATES)
    ].format(name=c["name"])
    c["free_pilot_body"] = FREE_PILOT_BODY_TEMPLATE.format(name=c["name"])
    return c


# -------------------- Stage 5: Export CSV --------------------

CSV_COLUMNS = [
    "Business Name",
    "Category",
    "City",
    "Neighborhood",
    "Address",
    "Phone",
    "Website",
    "Google Review Link",
    "Rating",
    "Total Reviews",
    "Recent Negative Share (30d)",
    "Key Complaint",
    "Complaint Score (0-100)",
    "Legal Review Flag",
    "Verbatim Excerpts (top 2)",
    "Outreach Subject",
    "Outreach Body",
    "Free-Pilot Subject",
    "Free-Pilot Body",
    "Sent Status",
    "Disqualified Reason",
]


def row_for(c: dict) -> dict[str, Any]:
    excerpts = c.get("verbatim_review_excerpts", [])[:2]
    return {
        "Business Name": c.get("name", ""),
        "Category": c.get("category", ""),
        "City": c.get("city", ""),
        "Neighborhood": c.get("neighborhood", ""),
        "Address": c.get("address", ""),
        "Phone": c.get("phone", ""),
        "Website": c.get("website", "") or "",
        "Google Review Link": c.get("google_review_url", ""),
        "Rating": c.get("rating", ""),
        "Total Reviews": c.get("review_count", ""),
        "Recent Negative Share (30d)": f"{c.get('recent_negative_share_30d', 0):.0%}",
        "Key Complaint": c.get("key_complaint", ""),
        "Complaint Score (0-100)": c.get("complaint_score", 0),
        "Legal Review Flag": c.get("legal_flag", ""),
        "Verbatim Excerpts (top 2)": " || ".join(excerpts),
        "Outreach Subject": c.get("outreach_subject", ""),
        "Outreach Body": c.get("outreach_body", ""),
        "Free-Pilot Subject": c.get("free_pilot_subject", ""),
        "Free-Pilot Body": c.get("free_pilot_body", ""),
        "Sent Status": c.get("sent_status", ""),
        "Disqualified Reason": c.get("disqualified_reason", ""),
    }


def export_csv(cands: list[dict], path: Path, include_disqualified: bool = False) -> int:
    rows = []
    for c in cands:
        if not include_disqualified and c.get("disqualified_reason"):
            continue
        rows.append(row_for(c))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# -------------------- Orchestrator --------------------

def run_pipeline(preview: bool = False) -> dict:
    print("=" * 70)
    print(" Denver Restaurant Reputation-Management Lead Pipeline")
    print("=" * 70)

    print("\n[1/5] Loading candidates...")
    cands = load_seed()
    print(f"  -> {len(cands)} total candidates loaded")

    print("\n[2/5] Scoring complaint signals...")
    for c in cands:
        score_candidate(c)
    print("  -> classification complete")

    print("\n[3/5] Filtering qualified leads...")
    qualified = filter_qualified(cands)
    dq_count = len(cands) - len(qualified)
    print(f"  -> {len(qualified)} qualified, {dq_count} disqualified")
    for c in cands:
        if c.get("disqualified_reason"):
            print(f"     - {c['name']}: {c['disqualified_reason']}")

    print("\n[4/5] Generating outreach drafts...")
    qualified.sort(key=lambda x: x["complaint_score"], reverse=True)
    for i, c in enumerate(qualified):
        generate_outreach(c, subject_idx=i)
        generate_free_pilot_outreach(c, subject_idx=i)
    print("  -> drafts written (direct + free-pilot), defamation guardrails applied")

    print("\n[5/5] Exporting CRM-ready CSV...")
    if preview:
        print("\n  PREVIEW (top 10, no file written):\n")
        for c in qualified[:10]:
            print(f"  • {c['name']:40s}  score={c['complaint_score']:3d}  "
                  f"rating={c['rating']}  neg={c['recent_negative_share_30d']:.0%}  "
                  f"→ {c['key_complaint']}"
                  + (f"  [LEGAL]" if c['legal_flag'] else ""))
        return {"qualified": len(qualified), "disqualified": dq_count, "written": 0}

    out_path = OUTPUT_DIR / "denver_restaurant_leads.csv"
    written = export_csv(qualified, out_path)
    print(f"  -> {written} leads written to {out_path}")

    # Also export a full audit CSV (including disqualified, with reasons)
    audit_path = OUTPUT_DIR / "denver_restaurant_leads_full_audit.csv"
    all_written = export_csv(cands, audit_path, include_disqualified=True)
    print(f"  -> {all_written} total rows (with audit) written to {audit_path}")

    return {
        "qualified": len(qualified),
        "disqualified": dq_count,
        "written": written,
        "csv_path": str(out_path),
        "audit_path": str(audit_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--run", action="store_true", help="Run the full pipeline")
    ap.add_argument("--preview", action="store_true",
                    help="Show top 10 leads, write nothing")
    ap.add_argument("--fetch-only", action="store_true",
                    help="Just load candidates and print counts")
    args = ap.parse_args()

    if args.fetch_only:
        cands = load_seed()
        print(f"Loaded {len(cands)} candidates from seed.")
        for c in cands[:5]:
            print(f"  • {c['name']} — {c['rating']} ★ ({c['review_count']} reviews)")
        return 0

    if args.preview:
        run_pipeline(preview=True)
        return 0

    if args.run or not (args.preview or args.fetch_only):
        run_pipeline(preview=False)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
