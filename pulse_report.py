"""
JetPakt Drift Monitor — PDF report renderer.

Takes a PulseInsight from pulse_engine and produces a single-page (weekly) or
two-page (monthly) PDF. Reuses scan_pdf fonts, palette, and page decor so
clients see a consistent brand across the one-time Operator Memo and the
recurring Drift Monitor reports.

The lead section surfaces the dominant operating pillar and the drift
direction (which pillar shifted, whether the peer gap widened or narrowed)
before the rating-delta banner, per REPOSITION_V3_SPEC.md §4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
)

from pulse_engine import PulseInsight
from scan_pdf import (
    BORDER, CREAM, ERROR, MUTED, TEAL, TEAL_DEEP, TEXT, WARN,
    _draw_wordmark_footer, build_styles, register_fonts, safe_para_text,
    severity_chip,
)


# ---------- Page decor (Pulse-specific header) ----------

def _pulse_page_decor(canvas, doc, account_name: str, cadence: str,
                      jetpakt_contact: dict[str, str]):
    from reportlab.lib.colors import HexColor
    canvas.saveState()
    w, h = letter
    # Cream page
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Top bar
    canvas.setFillColor(TEAL_DEEP)
    canvas.rect(0, h - 0.35 * inch, w, 0.35 * inch, fill=1, stroke=0)
    canvas.setFillColor(CREAM)
    try:
        canvas.setFont("DMSans", 9)
    except Exception:
        canvas.setFont("Helvetica-Bold", 9)
    tag = f"JETPAKT · DRIFT MONITOR · {cadence.upper()}"
    canvas.drawString(0.6 * inch, h - 0.22 * inch, tag)
    canvas.drawRightString(w - 0.6 * inch, h - 0.22 * inch, account_name.upper())
    # Footer
    canvas.setFillColor(MUTED)
    try:
        canvas.setFont("Inter", 8)
    except Exception:
        canvas.setFont("Helvetica", 8)
    footer = (f"{jetpakt_contact['name']} · "
              f"{jetpakt_contact['email']} · {jetpakt_contact['site']}")
    canvas.drawString(0.6 * inch, 0.35 * inch, footer)
    _draw_wordmark_footer(canvas, w, doc.page)
    canvas.restoreState()


# ---------- Severity helpers ----------

_SEVERITY_COLORS = {"HIGH": ERROR, "MED": WARN, "LOW": TEAL_DEEP}


def _severity_pill(level: str, S: dict) -> Table:
    """Small colored pill — HIGH / MED / LOW."""
    color = _SEVERITY_COLORS.get(level, TEAL_DEEP)
    p = Paragraph(f'<font color="white">{level}</font>', S["tag"])
    t = Table([[p]], colWidths=[0.55 * inch], rowHeights=[14])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# ---------- Section builders ----------

def _header(insight: PulseInsight, S: dict) -> list:
    cadence = insight.account.cadence.title()
    if insight.prior_date:
        period_line = f"Period: {insight.prior_date} → {insight.snapshot_date}"
    else:
        period_line = f"Baseline snapshot · {insight.snapshot_date}"
    story = [
        Paragraph(
            f"JETPAKT · DRIFT MONITOR · {cadence.upper()} DIGEST",
            S["cover_kicker"],
        ),
        Paragraph(safe_para_text(insight.account.name), S["cover_title"]),
        Paragraph(period_line, S["cover_sub"]),
        Spacer(1, 12),
    ]
    return story


def _drift_lead(insight: PulseInsight, S: dict) -> list:
    """Lead sentence: dominant pillar + drift direction.

    Sits above the rating-delta banner. Per REPOSITION_V3_SPEC.md §4, the
    pillar story is the headline; rating is a supporting KPI.
    """
    pillar = insight.dominant_pillar or "—"
    if insight.is_first_run:
        lead = (
            f"Dominant operating pillar this period is <b>{pillar}</b>. "
            f"This is the baseline — next cycle will compare against today."
        )
    else:
        # Derive drift-direction fragments from the change list.
        pillar_change = next(
            (c for c in (insight.changes or []) if c.kind == "pillar_shift"),
            None,
        )
        gap_widened = any(
            c.kind == "peer_gap_widened" for c in (insight.changes or [])
        )
        rating_change = next(
            (c for c in (insight.changes or [])
             if c.kind in ("rating_drop_high", "rating_drop", "rating_rise")),
            None,
        )

        if pillar_change is not None:
            pillar_phrase = (
                f"Dominant pillar shifted to <b>{pillar}</b> this period."
            )
        else:
            pillar_phrase = (
                f"Dominant pillar held on <b>{pillar}</b> this period."
            )

        direction_bits: list[str] = []
        if gap_widened:
            direction_bits.append("peer gap widened")
        if rating_change is not None:
            if rating_change.kind == "rating_rise":
                direction_bits.append("rating moved up")
            else:
                direction_bits.append("rating moved down")
        if not direction_bits:
            direction_bits.append("rating and peer gap held within drift")

        lead = (
            f"{pillar_phrase} Supporting movement: "
            f"{', '.join(direction_bits)}."
        )

    return [Paragraph(lead, S["body"]), Spacer(1, 8)]


def _snapshot_strip(insight: PulseInsight, S: dict) -> Table:
    """Four-up KPI strip: rating, reviews, severity, pillar."""
    from reportlab.lib.styles import ParagraphStyle

    # Smaller value style for text-heavy cells (pillar names, tier labels)
    kpi_value_sm = ParagraphStyle(
        "kpi_value_sm", parent=S["kpi_value"], fontSize=18, leading=22,
    )
    kpi_value_md = ParagraphStyle(
        "kpi_value_md", parent=S["kpi_value"], fontSize=24, leading=28,
    )

    def cell(val, label, style=None):
        v = Paragraph(str(val), style or S["kpi_value"])
        l = Paragraph(label, S["kpi_label"])
        return [v, Spacer(1, 4), l]

    pillar = insight.dominant_pillar or "—"
    # severity_chip returns "9.7 / 10 · HIGH" style labels — keep just the number+tier
    sev_num = f"{insight.executive_severity:.1f}"
    if insight.executive_severity >= 7.5:
        sev_tier = "HIGH"
    elif insight.executive_severity >= 4.5:
        sev_tier = "MED"
    else:
        sev_tier = "LOW"

    # Use Inter inline for the star so we don't hit InstrumentSerif tofu
    rating_str = (f'{insight.rating:.1f}<font name="Inter" size="22">\u2605</font>'
                  if insight.rating else "—")
    # Severity: number (big) + tier (smaller, inline) so both fit
    sev_str = f'{sev_num}<font name="Inter" size="11"> · {sev_tier}</font>'

    data = [[
        cell(rating_str, "Public rating"),
        cell(insight.review_count, "Total public reviews"),
        cell(sev_str, "Executive severity", kpi_value_md),
        cell(pillar, "Dominant pillar", kpi_value_sm),
    ]]
    t = Table(data, colWidths=[1.6 * inch] * 4, rowHeights=[1.05 * inch])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _overall_banner(insight: PulseInsight, S: dict) -> list:
    level = insight.overall_severity
    color = _SEVERITY_COLORS.get(level, TEAL_DEEP)
    if insight.is_first_run:
        msg = ("First Pulse cycle — establishing baseline. "
               "Next cycle will compare against today's snapshot.")
    elif level == "HIGH":
        msg = ("HIGH — material change detected. Same-day alert recommended; "
               "review the change list before any public action.")
    elif level == "MED":
        msg = ("MEDIUM — signals moved enough to adjust the 30/60/90 plan. "
               "No same-day action required.")
    else:
        msg = "LOW — metrics are steady. Keep executing the prior action plan."

    banner = Table([[
        _severity_pill(level, S),
        Paragraph(msg, S["body_small"]),
    ]], colWidths=[0.7 * inch, 5.8 * inch])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM),
        ("BOX", (0, 0), (-1, -1), 0.5, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [banner, Spacer(1, 12)]


def _changes_section(insight: PulseInsight, S: dict) -> list:
    """Ranked table of changes: pill · kind · description."""
    story: list = [Paragraph("What drifted", S["h2"])]
    if not insight.changes:
        story.append(Paragraph(
            "Nothing material drifted this cycle. Rating, signal severity, "
            "and peer position are within normal variation.", S["body"]))
        return story

    # Sort HIGH > MED > LOW
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    sorted_changes = sorted(insight.changes, key=lambda c: order.get(c.severity, 9))

    rows = []
    for c in sorted_changes:
        rows.append([
            _severity_pill(c.severity, S),
            Paragraph(safe_para_text(c.description), S["body_small"]),
        ])
    t = Table(rows, colWidths=[0.7 * inch, 5.8 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, BORDER),
    ]))
    story.append(t)
    return story


def _legal_panel(insight: PulseInsight, S: dict) -> list:
    flags = insight.legal_flags or []
    if not flags:
        return []
    lines = []
    for f in flags:
        sig = f.get("signal", "unknown signal")
        level = f.get("flag", "LEGAL")
        note = f.get("note", "")
        lines.append(
            f"<b>{level} · {sig}.</b> {safe_para_text(note)}"
        )
    body = "<br/><br/>".join(lines)
    panel = Paragraph(
        "<b>Legal review recommended.</b><br/><br/>" + body,
        S["legal"],
    )
    return [Spacer(1, 6), panel, Spacer(1, 8)]


def _next_cycle_note(insight: PulseInsight, S: dict) -> list:
    cadence = insight.account.cadence.lower()
    next_txt = "next Monday" if cadence == "weekly" else "the first of next month"
    routing = "client direct, Ryan CC'd"
    if insight.requires_same_day_alert:
        routing = "Ryan only (legal/HIGH routing active)"
    elif insight.account.effective_delivery_mode(False) == "ryan_only":
        routing = "Ryan only"
    return [
        Spacer(1, 10),
        Paragraph(
            f"Next cycle runs {next_txt}. Delivery for this cycle: {routing}. "
            "No reviews are solicited, replied to, or responded to without "
            "explicit owner approval.",
            S["muted"],
        ),
    ]


# ---------- Top-level render ----------

def render_pulse_pdf(insight: PulseInsight, output_path: str | Path) -> str:
    fonts = register_fonts()
    S = build_styles(fonts)

    jetpakt_contact = {
        "name": "Ryan B.",
        "email": "gojetpakt.us@outlook.com",
        "site": "Gojetpakt.com",
    }

    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        title=f"JetPakt Drift Monitor — {insight.account.name}",
        author="Perplexity Computer",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )

    def decor(c, d):
        _pulse_page_decor(c, d, insight.account.name,
                          insight.account.cadence, jetpakt_contact)

    doc.addPageTemplates([PageTemplate(id="pulse", frames=[frame], onPage=decor)])

    story: list = []
    story += _header(insight, S)
    story += _drift_lead(insight, S)
    story.append(_snapshot_strip(insight, S))
    story.append(Spacer(1, 12))
    story += _overall_banner(insight, S)
    story += _changes_section(insight, S)
    story += _legal_panel(insight, S)
    story += _next_cycle_note(insight, S)

    doc.build(story)
    return output_path
