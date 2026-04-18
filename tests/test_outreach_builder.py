"""
Tests for outreach_builder — guardrails and quote selection.

Run: python -m pytest tests/test_outreach_builder.py -q
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outreach_builder import (  # noqa: E402
    build_draft,
    extract_primary_quote,
    classify_legal_severity,
    describe_pillar,
    _is_blocked,
)


# ---------------------------------------------------------------------------
# Defamation / safety guardrails
# ---------------------------------------------------------------------------
def test_illness_quote_is_blocked():
    assert _is_blocked("EVERY ONE OF US went down with food poisoning after eating here.")
    assert _is_blocked("Made me sick — never again.")
    assert _is_blocked("Ended up in the hospital that night.")


def test_safe_quote_is_not_blocked():
    assert not _is_blocked("The 22% automatic service fee was not disclosed on the menu.")
    assert not _is_blocked("Ten years ago it was one of my favorite places — the quality has completely slipped.")


def test_extract_picks_pillar_matching_quote():
    # Service-fee pillar should pick the service-fee quote, NOT the price/value one.
    excerpts = (
        "Paid $45 per person and left hungry — food quality does not match the ticket price. "
        "|| Was never told about the 15% automatic service charge until the bill arrived."
    )
    q = extract_primary_quote(excerpts, key_complaint="billing / service-fee transparency")
    assert "automatic service charge" in q
    assert "$45 per person" not in q


def test_extract_skips_blocked_quote_and_picks_alternate():
    # First quote is an illness allegation — must be skipped.
    excerpts = (
        "EVERY ONE OF US went down with food poisoning after eating here. "
        "|| Ten years ago it was one of my favorite places — the quality has completely slipped."
    )
    q = extract_primary_quote(excerpts, key_complaint="food safety perception")
    assert "food poisoning" not in q
    assert "favorite places" in q


def test_extract_returns_empty_when_all_quotes_blocked():
    excerpts = "Got food poisoning. || Made me sick and I had to go to the hospital."
    q = extract_primary_quote(excerpts, key_complaint="food safety perception")
    assert q == ""


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------
def test_classify_legal_severity():
    assert classify_legal_severity("HIGH — wage/service-fee disclosure") == "HIGH"
    assert classify_legal_severity("medium concern") == "MED"
    assert classify_legal_severity("") == "NONE"
    assert classify_legal_severity("something else") == "NONE"


# ---------------------------------------------------------------------------
# Pillar description
# ---------------------------------------------------------------------------
def test_describe_pillar_service_fee():
    d = describe_pillar("billing / service-fee transparency")
    assert "service fees" in d.lower()


def test_describe_pillar_food_quality_does_not_match_service_fee_tokens():
    # Regression guard: service_attentiveness used to match bare "service" and
    # would collide with "service-fee" strings. Ensure billing/service-fee wins.
    d = describe_pillar("billing / service-fee transparency")
    assert "service fees" in d.lower()
    assert "attentiveness" not in d.lower()


# ---------------------------------------------------------------------------
# Full draft integration
# ---------------------------------------------------------------------------
def _example_row(**overrides):
    base = {
        "Business Name": "Example Eatery",
        "Category": "American",
        "Neighborhood": "RiNo",
        "Rating": "3.4",
        "Key Complaint": "billing / service-fee transparency",
        "Legal Review Flag": "HIGH — service-fee disclosure",
        "Verbatim Excerpts (top 2)": "Good vibes though. || The 22% automatic service fee was not disclosed.",
    }
    base.update(overrides)
    return base


def test_build_draft_includes_quote_and_signature():
    d = build_draft(_example_row())
    assert d.legal_flag_severity == "HIGH"
    assert '"The 22% automatic service fee was not disclosed."' in d.body
    assert "Ryan B." in d.body
    assert "303-549-1697" in d.body
    assert d.to_email == ""  # always empty — user fills


def test_build_draft_no_individual_names_leaked():
    # Guard: the body must never contain first-name-looking leaks outside quotes.
    # Project rule: reviewer first names OK only inside verbatim quotes.
    d = build_draft(_example_row())
    # Check that no "Hi [Name]," style leaks happened
    assert "Hi Ryan," not in d.body
    assert "Dear Mr." not in d.body


def test_build_draft_legal_flag_note_only_for_high():
    d_high = build_draft(_example_row(**{"Legal Review Flag": "HIGH"}))
    d_none = build_draft(_example_row(**{"Legal Review Flag": ""}))
    assert "HB25-1090" in d_high.body
    assert "HB25-1090" not in d_none.body


def test_build_draft_handles_no_safe_quote():
    row = _example_row(**{
        "Verbatim Excerpts (top 2)": "Got food poisoning. || Made me sick.",
        "Key Complaint": "food safety perception",
        "Legal Review Flag": "HIGH",
    })
    d = build_draft(row)
    # Must not embed any blocked quote
    assert "food poisoning" not in d.body.lower()
    assert "made me sick" not in d.body.lower()
    # Must still produce a coherent body (falls back to pillar-only framing)
    assert "preview" in d.body.lower()
    assert "Ryan B." in d.body
