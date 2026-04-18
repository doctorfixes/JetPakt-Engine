"""
Tests for outreach_builder (template v2).

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
    is_positive_quote_usable,
    _is_blocked,
    _has_em_dash,
    _shorten_business_name_for_subject,
    _strip_em_dashes_outside_quotes,
    SUBJECT_MAX_CHARS,
    EM_DASH,
)


# ---------------------------------------------------------------------------
# Defamation / safety guardrails
# ---------------------------------------------------------------------------
def test_illness_quote_is_blocked():
    assert _is_blocked("EVERY ONE OF US went down with food poisoning after eating here.")
    assert _is_blocked("Made me sick, never again.")
    assert _is_blocked("Ended up in the hospital that night.")


def test_safe_quote_is_not_blocked():
    assert not _is_blocked("The 22% automatic service fee was not disclosed on the menu.")
    assert not _is_blocked("The pizza was undercooked and the cheese tasted off.")


def test_driveby_rating_is_blocked():
    # '0/10' is blocked as low-signal drive-by language
    assert _is_blocked("0/10 would recommend, absolutely terrible.")


def test_extract_picks_pillar_matching_quote():
    excerpts = (
        "Paid $45 per person and left hungry. "
        "|| Was never told about the 15% automatic service charge until the bill arrived."
    )
    q = extract_primary_quote(excerpts, key_complaint="billing / service-fee transparency")
    assert "automatic service charge" in q
    assert "$45 per person" not in q


def test_extract_skips_blocked_quote_and_picks_alternate():
    excerpts = (
        "EVERY ONE OF US went down with food poisoning after eating here. "
        "|| Ten years ago it was one of my favorite places, the quality has completely slipped."
    )
    q = extract_primary_quote(excerpts, key_complaint="food safety perception")
    assert "food poisoning" not in q
    assert "favorite places" in q


def test_extract_returns_empty_when_all_quotes_blocked():
    excerpts = "Got food poisoning. || Made me sick and I had to go to the hospital."
    q = extract_primary_quote(excerpts, key_complaint="food safety perception")
    assert q == ""


def test_extract_prefers_non_em_dash_quote_when_scores_tie():
    # Both quotes match the food_quality pillar; one has an em-dash, one does not.
    excerpts = (
        "The food quality slipped \u2014 not the same place. "
        "|| The food quality slipped and it was very salty."
    )
    q = extract_primary_quote(excerpts, key_complaint="food quality")
    # The non-em-dash quote should be preferred.
    assert "\u2014" not in q
    assert "salty" in q


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------
def test_classify_legal_severity():
    assert classify_legal_severity("HIGH, wage/service-fee disclosure") == "HIGH"
    assert classify_legal_severity("medium concern") == "MED"
    assert classify_legal_severity("") == "NONE"
    assert classify_legal_severity("something else") == "NONE"


# ---------------------------------------------------------------------------
# Pillar framing
# ---------------------------------------------------------------------------
def test_describe_pillar_service_fee():
    d = describe_pillar("billing / service-fee transparency")
    assert "service fee" in d.lower()


def test_describe_pillar_is_em_dash_free():
    # Every pre-written pillar framing must be em-dash free.
    for key in [
        "billing / service-fee transparency",
        "wait time",
        "food quality",
        "service attentiveness",
        "noise",
        "price-to-value",
        "cleanliness",
        "slow service",
        "server attitude",
        "inconsistent recent guest experience",
    ]:
        assert not _has_em_dash(describe_pillar(key)), f"em-dash found in pillar: {key}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_shorten_business_name_drops_location_suffix():
    assert _shorten_business_name_for_subject("Big Daddy's Pizza \u2014 Colfax") == "Big Daddy's Pizza"
    assert _shorten_business_name_for_subject("El Tapatio, Arvada") == "El Tapatio"
    assert _shorten_business_name_for_subject("Sam's No. 3") == "Sam's No. 3"


def test_strip_em_dashes_outside_quote_lines():
    body = (
        "This is an em-dash sentence \u2014 and another.\n\n"
        "    \"Verbatim quote \u2014 keep this one\"\n\n"
        "Closing line \u2014 should be stripped."
    )
    out = _strip_em_dashes_outside_quotes(body)
    assert "em-dash sentence ," in out
    assert "Closing line ," in out
    # The quote line must retain its em-dash
    assert "\"Verbatim quote \u2014 keep this one\"" in out


# ---------------------------------------------------------------------------
# Full draft integration (template v2)
# ---------------------------------------------------------------------------
def _example_row(**overrides):
    base = {
        "Business Name": "Example Eatery",
        "Category": "American",
        "Neighborhood": "RiNo",
        "Rating": "3.4",
        "Total Reviews": "412",
        "Key Complaint": "billing / service-fee transparency",
        "Legal Review Flag": "HIGH, service-fee disclosure",
        "Verbatim Excerpts (top 2)": "Good vibes though. || The 22% automatic service fee was not disclosed.",
    }
    base.update(overrides)
    return base


def test_build_draft_includes_quote_and_signature():
    d = build_draft(_example_row())
    assert d.legal_flag_severity == "HIGH"
    assert '"The 22% automatic service fee was not disclosed."' in d.body
    assert "Ryan B." in d.body
    assert "gojetpakt.us@outlook.com" in d.body
    assert "303-549-1697" not in d.body  # phone removed from all messaging
    assert d.to_email == ""


def test_build_draft_body_contains_review_count_in_opening():
    d = build_draft(_example_row())
    assert "412 public reviews" in d.body
    assert "Example Eatery" in d.body


def test_build_draft_body_has_no_em_dashes_outside_quotes():
    d = build_draft(_example_row())
    # Split body on quote lines and verify the non-quote portions are em-dash free
    for line in d.body.split("\n"):
        if line.startswith('    "'):
            continue
        assert EM_DASH not in line, f"em-dash found in non-quote line: {line!r}"


def test_build_draft_no_individual_names_leaked():
    d = build_draft(_example_row())
    assert "Hi Ryan," not in d.body
    assert "Dear Mr." not in d.body


def test_build_draft_legal_flag_note_only_for_high():
    d_high = build_draft(_example_row(**{"Legal Review Flag": "HIGH"}))
    d_none = build_draft(_example_row(**{"Legal Review Flag": ""}))
    # Template v2 writes "HB25 1090" (space, not hyphen) to avoid hyphens in body
    assert "HB25 1090" in d_high.body
    assert "HB25 1090" not in d_none.body


def test_build_draft_handles_no_safe_quote():
    row = _example_row(**{
        "Verbatim Excerpts (top 2)": "Got food poisoning. || Made me sick.",
        "Key Complaint": "food safety perception",
        "Legal Review Flag": "HIGH",
    })
    d = build_draft(row)
    assert "food poisoning" not in d.body.lower()
    assert "made me sick" not in d.body.lower()
    assert "preview" in d.body.lower()
    assert "Ryan B." in d.body


def test_build_draft_subject_is_short():
    d = build_draft(_example_row())
    assert len(d.subject) <= SUBJECT_MAX_CHARS
    assert EM_DASH not in d.subject


def test_build_draft_subject_uses_short_name():
    d = build_draft(_example_row(**{"Business Name": "Big Daddy's Pizza \u2014 Colfax"}))
    assert d.subject == "A pattern in Big Daddy's Pizza reviews"
    assert len(d.subject) <= SUBJECT_MAX_CHARS


def test_build_draft_signature_is_two_lines():
    d = build_draft(_example_row())
    # The signature appears at the very end of the body.
    sig_lines = d.body.rstrip().split("\n")[-2:]
    assert sig_lines[0] == "Ryan B., JetPakt Solutions (Denver)"
    assert "gojetpakt.us@outlook.com" in sig_lines[1]
    assert "gojetpakt.com" in sig_lines[1]


def test_build_draft_offer_is_binary():
    d = build_draft(_example_row())
    assert "Reply \"yes\"" in d.body
    assert "within two business days" in d.body
    assert "$49" in d.body


# ---------------------------------------------------------------------------
# Positive sentiment (Option A opener)
# ---------------------------------------------------------------------------
def test_is_positive_quote_usable_accepts_authentic():
    assert is_positive_quote_usable(
        "The patio is arranged to look like the outside of a cabin with fire pits."
    )
    assert is_positive_quote_usable(
        "Fried dumplings was really good along with the Mongolian grill."
    )


def test_is_positive_quote_usable_rejects_defamation_tokens():
    # Safety filter applies to positives too (in case of mislabeled review scraping)
    assert not is_positive_quote_usable("Loved it even though I got sick after dinner.")
    assert not is_positive_quote_usable("")
    assert not is_positive_quote_usable("   ")


def test_is_positive_quote_usable_rejects_testimonial_phrasing():
    assert not is_positive_quote_usable("I highly recommend to everyone in Denver.")
    assert not is_positive_quote_usable("Best restaurant in the world, hands down.")
    assert not is_positive_quote_usable("5 stars all the way, every visit.")


def test_build_draft_uses_positive_opener_when_available():
    row = _example_row(**{
        "Positive Theme": "neighborhood patio spot",
        "Positive Verbatim Quote": "The patio is the reason we keep coming back on Sundays.",
    })
    d = build_draft(row)
    # Positive opener phrase present
    assert "Before the concern, the good news" in d.body
    # Positive theme interpolated
    assert "neighborhood patio spot" in d.body
    # Positive quote present and indented as a quote block
    assert '"The patio is the reason we keep coming back on Sundays."' in d.body
    # Bridge to negative
    assert "That is the part worth protecting" in d.body
    # Negative quote still present
    assert "automatic service fee" in d.body.lower()


def test_build_draft_falls_back_to_neutral_opener_when_positive_missing():
    # Default example row has no positive fields
    d = build_draft(_example_row())
    assert "Before the concern, the good news" not in d.body
    assert "I spent part of this week reading" in d.body


def test_build_draft_positive_opener_has_no_em_dashes_in_generated_text():
    row = _example_row(**{
        "Positive Theme": "neighborhood patio spot",
        "Positive Verbatim Quote": "The patio is the reason we keep coming back on Sundays.",
    })
    d = build_draft(row)
    for line in d.body.split("\n"):
        if line.startswith('    "'):
            continue
        assert EM_DASH not in line, f"em-dash found in non-quote line: {line!r}"


def test_build_draft_falls_back_when_positive_quote_is_blocked():
    # Blocked positive quote (contains a defamation token) should cause fallback
    row = _example_row(**{
        "Positive Theme": "neighborhood patio spot",
        "Positive Verbatim Quote": "Loved it even though I got sick after dinner.",
    })
    d = build_draft(row)
    assert "Before the concern, the good news" not in d.body
    assert "got sick" not in d.body.lower()
