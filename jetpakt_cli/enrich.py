"""Enrichment module.

Two pipelines, same plan/apply pattern as inbox.py and clients.py:

1. refresh-ratings — takes the Prospects roster and live Google Places
   results (one JSON list fetched by the agent), diffs against the stored
   rating / review_count, and emits Prospects update actions for every row
   that drifted by at least 0.3 stars or 50 reviews (thresholds configurable).

2. enrich-emails — takes the roster rows missing owner_email and a JSON list
   of Hunter domain-search results, and emits Prospects update actions for
   every row where Hunter returned a confidence >= 70 email.

Both pipelines are purely deterministic Python. The agent does the connector
calls (Places lookup, Hunter search) and feeds normalized JSON in.

Input schemas:
  - places_hits.json: list of
    {prospect_id, live_rating: float, live_review_count: int, live_website,
     place_id (optional), last_updated_iso}
  - hunter_hits.json: list of
    {prospect_id, domain, first_name, last_name, position, email,
     confidence: int, source_url}

Output: update plan matching the Prospects 26-col schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config as cfg
from .clients import ProspectLite  # reuse shape


# Drift thresholds for flagging a refresh. Below these deltas we don't
# bother writing, to keep the audit log quiet.
RATING_DRIFT_MIN = 0.3           # stars
REVIEW_COUNT_DRIFT_MIN = 50      # absolute
REVIEW_COUNT_DRIFT_PCT = 0.05    # 5% change also triggers

# Hunter confidence floor. Below this we treat a hit as "not found" to avoid
# poisoning the roster with speculative emails.
HUNTER_CONFIDENCE_MIN = 70


@dataclass(frozen=True)
class ProspectFull:
    """Full 26-col Prospects row, indexed positionally."""
    prospect_id: str
    business_name: str
    category: str
    neighborhood: str
    city: str
    state: str
    rating: str
    review_count: str
    peer_gap: str
    rating_12mo_delta: str
    priority_tier: str
    dominant_pillar: str
    ros_case_id: str
    legal_flag_severity: str
    google_url: str
    yelp_url: str
    website: str
    owner_name: str
    owner_email: str
    source: str
    stage: str
    stage_entered_at: str
    next_action_due: str
    notes: str
    created_at: str
    updated_at: str

    @staticmethod
    def from_row(row: List[str]) -> "ProspectFull":
        padded = list(row) + [""] * (26 - len(row))
        return ProspectFull(*padded[:26])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -----------------------------------------------------------------------
# Loaders
# -----------------------------------------------------------------------

def load_prospects_full(path: Path) -> List[ProspectFull]:
    """Load prospects from the full 26-col dump the cron uses.

    Expected JSON shape: list of objects keyed by the Prospects column
    names (same as google_sheets-read-rows hasHeaders=true output).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: List[ProspectFull] = []
    cols = [
        "prospect_id", "business_name", "category", "neighborhood", "city",
        "state", "rating", "review_count", "peer_gap", "rating_12mo_delta",
        "priority_tier", "dominant_pillar", "ros_case_id",
        "legal_flag_severity", "google_url", "yelp_url", "website",
        "owner_name", "owner_email", "source", "stage", "stage_entered_at",
        "next_action_due", "notes", "created_at", "updated_at",
    ]
    for p in raw:
        out.append(ProspectFull(*(str(p.get(c, "")) for c in cols)))
    return out


# -----------------------------------------------------------------------
# Rating refresh
# -----------------------------------------------------------------------

def _parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip()) if str(s).strip() else None
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip()) if str(s).strip() else None
    except ValueError:
        return None


def _rating_drifted(stored: Optional[float], live: float) -> bool:
    if stored is None:
        return True
    return abs(live - stored) >= RATING_DRIFT_MIN


def _review_count_drifted(stored: Optional[int], live: int) -> bool:
    if stored is None or stored == 0:
        return live > 0
    delta = abs(live - stored)
    if delta >= REVIEW_COUNT_DRIFT_MIN:
        return True
    return (delta / max(stored, 1)) >= REVIEW_COUNT_DRIFT_PCT


def build_refresh_plan(prospects: List[ProspectFull],
                       places_hits: List[Dict[str, Any]],
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Emit Prospects updates for rows whose rating/review_count drifted."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    prospects_by_id = {p.prospect_id: p for p in prospects}
    hits_by_id: Dict[str, Dict[str, Any]] = {}
    for h in places_hits:
        pid = h.get("prospect_id")
        if pid:
            hits_by_id[pid] = h

    updates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    unmatched: List[str] = [pid for pid in hits_by_id if pid not in prospects_by_id]

    for pid, hit in hits_by_id.items():
        p = prospects_by_id.get(pid)
        if p is None:
            continue
        live_rating = hit.get("live_rating")
        live_count = hit.get("live_review_count")
        live_website = (hit.get("live_website") or "").strip()

        stored_rating = _parse_float(p.rating)
        stored_count = _parse_int(p.review_count)

        rating_d = live_rating is not None and _rating_drifted(stored_rating, float(live_rating))
        count_d = live_count is not None and _review_count_drifted(stored_count, int(live_count))
        website_d = bool(live_website) and live_website != (p.website or "").strip()

        if not (rating_d or count_d or website_d):
            skipped.append({
                "prospect_id": pid,
                "reason": "no_drift",
                "stored_rating": stored_rating,
                "live_rating": live_rating,
                "stored_review_count": stored_count,
                "live_review_count": live_count,
            })
            continue

        note_parts = []
        if rating_d:
            note_parts.append(
                f"rating {stored_rating or '--'} -> {live_rating}"
            )
        if count_d:
            note_parts.append(
                f"reviews {stored_count or 0} -> {live_count}"
            )
        if website_d:
            note_parts.append("website updated")
        notes_append = f"Refresh {now_iso}: " + "; ".join(note_parts)

        set_block = {
            "notes_append": notes_append,
            "updated_at": now_iso,
        }
        if rating_d:
            set_block["rating"] = f"{float(live_rating):.1f}"
        if count_d:
            set_block["review_count"] = str(int(live_count))
        if website_d:
            set_block["website"] = live_website

        updates.append({
            "find": {"column": "A", "value": pid},
            "set": set_block,
        })

    return {
        "generated_at": now_iso,
        "prospect_updates": updates,
        "skipped": skipped,
        "unmatched_hits": unmatched,
        "summary": {
            "hits_checked": len(hits_by_id),
            "updates": len(updates),
            "skipped_no_drift": len(skipped),
            "unmatched": len(unmatched),
            "rating_drift_min": RATING_DRIFT_MIN,
            "review_count_drift_min": REVIEW_COUNT_DRIFT_MIN,
        },
    }


# -----------------------------------------------------------------------
# Email enrichment
# -----------------------------------------------------------------------

def build_enrich_plan(prospects: List[ProspectFull],
                      hunter_hits: List[Dict[str, Any]],
                      missing_only: bool = True,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """Emit Prospects updates where Hunter found a high-confidence email.

    missing_only: if True (default), only update rows where owner_email is
    empty. If False, still check high-confidence hits but leave existing
    emails alone (never overwrite a proven address).
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    prospects_by_id = {p.prospect_id: p for p in prospects}

    # Index Hunter hits by prospect_id, keeping only the best (highest
    # confidence) hit per prospect.
    best_by_id: Dict[str, Dict[str, Any]] = {}
    for h in hunter_hits:
        pid = h.get("prospect_id")
        conf = int(h.get("confidence") or 0)
        if not pid or conf < HUNTER_CONFIDENCE_MIN:
            continue
        prev = best_by_id.get(pid)
        if prev is None or conf > int(prev.get("confidence") or 0):
            best_by_id[pid] = h

    updates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for pid, hit in best_by_id.items():
        p = prospects_by_id.get(pid)
        if p is None:
            skipped.append({"prospect_id": pid, "reason": "unmatched_prospect"})
            continue
        existing_email = (p.owner_email or "").strip()
        if missing_only and existing_email:
            skipped.append({
                "prospect_id": pid, "reason": "already_has_email",
                "existing_email": existing_email,
                "hunter_email": hit.get("email"),
            })
            continue

        email = (hit.get("email") or "").strip()
        if not email:
            skipped.append({"prospect_id": pid, "reason": "hit_missing_email"})
            continue

        first = (hit.get("first_name") or "").strip()
        last = (hit.get("last_name") or "").strip()
        position = (hit.get("position") or "").strip()
        name_parts = [x for x in [first, last] if x]
        name = " ".join(name_parts)

        note = f"Enrich {now_iso}: Hunter conf={hit.get('confidence')} {email}"
        if position:
            note += f" ({position})"

        set_block = {
            "owner_email": email,
            "notes_append": note,
            "updated_at": now_iso,
        }
        if name and not (p.owner_name or "").strip():
            set_block["owner_name"] = name

        updates.append({
            "find": {"column": "A", "value": pid},
            "set": set_block,
            "_source": {
                "confidence": hit.get("confidence"),
                "source_url": hit.get("source_url"),
            },
        })

    return {
        "generated_at": now_iso,
        "prospect_updates": updates,
        "skipped": skipped,
        "summary": {
            "hunter_hits": len(hunter_hits),
            "passing_confidence_floor": len(best_by_id),
            "updates": len(updates),
            "skipped": len(skipped),
            "confidence_floor": HUNTER_CONFIDENCE_MIN,
            "missing_only": missing_only,
        },
    }
