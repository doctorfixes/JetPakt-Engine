"""
JetPakt Drift Monitor — delivery module.

Takes a rendered PulseInsight + PDF path and produces a structured draft
payload ready for the Outlook connector. We never auto-send; the caller
is expected to pass the payload to the outlook connector in "draft" mode
(create_draft / save_as_draft), or the CLI can dump it to disk for human
review.

Design constraints (preserved from the project-wide rules):
- Drafts only — never send directly.
- No individuals named in body copy (first names only inside verbatim
  reviewer quotes, which Pulse digests do NOT include).
- Legal-HIGH events always route ryan_only; Legal-MED inherits account
  default routing.
- Per-row approval gate: the caller decides when (or whether) to send.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from pulse_engine import PulseInsight


# ---------- Draft payload ----------

@dataclass
class DraftPayload:
    """Everything needed to create one Outlook draft.

    The outlook connector's create_draft tool expects: to, cc, subject,
    body (HTML), and optional attachments. We return this as a plain dict
    via as_outlook_args() so the caller can adapt to whatever the
    connector schema turns out to be.
    """
    account_id: str
    to: list[str]
    cc: list[str]
    subject: str
    body_html: str
    body_text: str
    attachments: list[str]
    routing_reason: str          # human-readable explanation of the routing
    requires_human_review: bool  # True for HIGH severity, legal-HIGH, etc.
    meta: dict[str, Any] = field(default_factory=dict)

    def as_outlook_args(self) -> dict[str, Any]:
        """Flatten to a dict suitable for outlook create_draft.

        Exact parameter names depend on the connector schema — the caller
        should adapt. Keys here match the common Graph-style schema.
        """
        return {
            "to": self.to,
            "cc": self.cc,
            "subject": self.subject,
            "body": self.body_html,
            "body_type": "html",
            "attachments": self.attachments,
        }


# ---------- Copy templates ----------

_SALUTATION = "Hi team,"  # no individual names, per project rule

_BOILERPLATE_CLOSING_HTML = (
    '<p style="color:#6b6b6b;font-size:12px">'
    "This is a JetPakt Drift Monitor digest — a recurring readout of the "
    "dominant operating pillar, drift direction, and any new Restaurant "
    "Operating System case matches. We never solicit, reply to, or respond "
    "to reviews without your explicit approval. Every claim above is tied "
    "to verbatim public reviews available in the attached PDF."
    "</p>"
    '<p style="color:#6b6b6b;font-size:12px">'
    "Ryan B. · "
    '<a href="mailto:gojetpakt.us@outlook.com">gojetpakt.us@outlook.com</a> · '
    '<a href="https://Gojetpakt.com">Gojetpakt.com</a>'
    "</p>"
)

_BOILERPLATE_CLOSING_TEXT = (
    "\n--\nThis is a JetPakt Drift Monitor digest — a recurring readout of "
    "the dominant operating pillar, drift direction, and any new Restaurant "
    "Operating System case matches. We never solicit, reply to, or respond "
    "to reviews without your explicit approval. Every claim above is tied "
    "to verbatim public reviews available in the attached PDF.\n\n"
    "Ryan B. · gojetpakt.us@outlook.com · Gojetpakt.com\n"
)


# ---------- Subject & body builders ----------

def _subject_for(insight: PulseInsight) -> str:
    name = insight.account.name
    cadence = insight.account.cadence.title()
    date = insight.snapshot_date

    if insight.is_first_run:
        return f"JetPakt Drift Monitor — {name} — baseline ({date})"
    if insight.overall_severity == "HIGH":
        return f"[ALERT] JetPakt Drift Monitor — {name} — pillar drift ({date})"
    if insight.overall_severity == "MED":
        return f"JetPakt Drift Monitor — {name} — signals drifted ({date})"
    return f"JetPakt Drift Monitor — {name} — {cadence} digest ({date})"


def _summary_lines(insight: PulseInsight) -> list[str]:
    """Plain-English 3-5 line summary, no names, claim-by-claim."""
    lines: list[str] = []
    name = insight.account.name

    if insight.is_first_run:
        lines.append(
            f"This is the first Pulse cycle for {name} — today's snapshot "
            f"(rating {insight.rating:.1f}★, {insight.review_count} public reviews, "
            f"executive severity {insight.executive_severity:.1f}/10) is now "
            f"the baseline. Future cycles will compare against it."
        )
    else:
        lines.append(
            f"Pulse {insight.account.cadence} readout for {name} — "
            f"{insight.snapshot_date} vs prior {insight.prior_date}."
        )

    # Severity summary
    if insight.overall_severity == "HIGH":
        lines.append(
            "Overall signal: HIGH — one or more material changes detected. "
            "Review recommended before any public action."
        )
    elif insight.overall_severity == "MED":
        lines.append(
            "Overall signal: MEDIUM — signals moved enough to adjust the "
            "30/60/90 plan. No same-day action required."
        )
    elif not insight.is_first_run:
        lines.append(
            "Overall signal: LOW — metrics are steady. Keep executing the "
            "prior action plan."
        )

    # Top 2 changes (HIGH > MED > LOW)
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    top = sorted(insight.changes, key=lambda c: order.get(c.severity, 9))[:2]
    for c in top:
        if c.severity == "LOW" and insight.is_first_run:
            continue  # boilerplate first-run change — already covered above
        lines.append(f"• [{c.severity}] {c.description}")

    # Legal flags summary (no names, no specifics past the flag itself)
    has_legal_high = any(f.get("flag") == "LEGAL-HIGH" for f in insight.legal_flags)
    if has_legal_high:
        lines.append(
            "Legal-HIGH item active — routing this digest to Ryan only; "
            "we will not copy the client until legal review is complete."
        )
    elif insight.legal_flags:
        lines.append(
            "Legal-MED item active — items noted in the PDF benefit from a "
            "quick legal review before any public response is drafted."
        )

    return lines


def _body_html(insight: PulseInsight, summary_lines: list[str],
               pdf_filename: str) -> str:
    bullets = "".join(
        f'<li style="margin-bottom:4px">{_escape(line.lstrip("• ").strip())}</li>'
        for line in summary_lines[1:]  # first line used as lead paragraph
    )
    lead = _escape(summary_lines[0])

    return (
        f'<div style="font-family:Inter,Arial,sans-serif;color:#28251d;'
        f'font-size:14px;line-height:1.55;max-width:620px">'
        f"<p>{_SALUTATION}</p>"
        f"<p>{lead}</p>"
        f'<ul style="padding-left:18px;margin:8px 0 12px 0">{bullets}</ul>'
        f'<p>Full readout, verbatim review excerpts, and recommended next '
        f"steps are in the attached PDF ({_escape(pdf_filename)}).</p>"
        f"<p>Reply to approve, adjust, or skip any recommended action.</p>"
        f"{_BOILERPLATE_CLOSING_HTML}"
        f"</div>"
    )


def _body_text(insight: PulseInsight, summary_lines: list[str],
               pdf_filename: str) -> str:
    head = f"{_SALUTATION}\n\n{summary_lines[0]}\n\n"
    bullets = "\n".join(
        line if line.startswith("•") else f"  {line}"
        for line in summary_lines[1:]
    )
    tail = (
        f"\n\nFull readout, verbatim review excerpts, and recommended next "
        f"steps are in the attached PDF ({pdf_filename}).\n\n"
        f"Reply to approve, adjust, or skip any recommended action."
    )
    return head + bullets + tail + _BOILERPLATE_CLOSING_TEXT


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------- Routing ----------

def _route(insight: PulseInsight) -> tuple[list[str], list[str], str]:
    """Return (to, cc, reason) for this insight.

    Rules:
      - Legal-HIGH OR overall HIGH severity ⇒ ryan_only (Ryan in To).
      - client_cc_ryan ⇒ client in To, Ryan CC'd.
      - ryan_only (account default) ⇒ Ryan in To.
      - Missing client_email falls back to ryan_only.
    """
    acct = insight.account
    has_legal_high = any(f.get("flag") == "LEGAL-HIGH" for f in insight.legal_flags)
    force_ryan_only = has_legal_high or insight.overall_severity == "HIGH"

    if force_ryan_only:
        if has_legal_high:
            reason = ("Legal-HIGH item present — routed to Ryan only; client "
                      "will be looped in after legal review.")
        else:
            reason = ("HIGH overall severity — routed to Ryan only for "
                      "human review before client delivery.")
        return [acct.ryan_email], [], reason

    mode = acct.effective_delivery_mode(has_legal_high=False)
    if mode == "client_cc_ryan" and acct.client_email:
        return [acct.client_email], [acct.ryan_email], "Client direct, Ryan CC'd."
    return [acct.ryan_email], [], "Ryan only (account default or no client email on file)."


# ---------- Public API ----------

def build_draft(insight: PulseInsight, pdf_path: str | Path) -> DraftPayload:
    """Compose a DraftPayload from a PulseInsight and its rendered PDF."""
    pdf_path = str(pdf_path)
    pdf_filename = Path(pdf_path).name

    to, cc, reason = _route(insight)
    summary = _summary_lines(insight)

    has_legal_high = any(f.get("flag") == "LEGAL-HIGH" for f in insight.legal_flags)
    requires_review = (
        insight.overall_severity == "HIGH"
        or insight.requires_same_day_alert
        or has_legal_high
    )

    return DraftPayload(
        account_id=insight.account.account_id,
        to=to,
        cc=cc,
        subject=_subject_for(insight),
        body_html=_body_html(insight, summary, pdf_filename),
        body_text=_body_text(insight, summary, pdf_filename),
        attachments=[pdf_path],
        routing_reason=reason,
        requires_human_review=requires_review,
        meta={
            "snapshot_date": insight.snapshot_date,
            "prior_date": insight.prior_date,
            "overall_severity": insight.overall_severity,
            "has_legal_high": has_legal_high,
            "is_first_run": insight.is_first_run,
            "cadence": insight.account.cadence,
            "tier": insight.account.tier,
        },
    )


def write_draft_to_disk(payload: DraftPayload, out_dir: str | Path) -> str:
    """Write a human-reviewable .md preview of the draft.

    This is what the CLI uses by default — draft files accumulate in
    output/pulse/drafts/ until Ryan explicitly approves and sends.
    No auto-send, ever.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{payload.account_id}_{payload.meta['snapshot_date']}.md"
    path = out_dir / fname

    to_line = ", ".join(payload.to) or "(no recipient)"
    cc_line = ", ".join(payload.cc) or "(none)"
    review_tag = " · REQUIRES HUMAN REVIEW" if payload.requires_human_review else ""

    md = [
        f"# Pulse draft · {payload.account_id} · {payload.meta['snapshot_date']}{review_tag}",
        "",
        f"- **To:** {to_line}",
        f"- **Cc:** {cc_line}",
        f"- **Subject:** {payload.subject}",
        f"- **Routing reason:** {payload.routing_reason}",
        f"- **Overall severity:** {payload.meta['overall_severity']}",
        f"- **Legal-HIGH present:** {payload.meta['has_legal_high']}",
        f"- **Attachments:** {', '.join(payload.attachments)}",
        "",
        "---",
        "",
        "## Body (plain text)",
        "",
        "```",
        payload.body_text,
        "```",
        "",
        "## Body (HTML, rendered in email client)",
        "",
        payload.body_html,
        "",
    ]
    path.write_text("\n".join(md))
    return str(path)
