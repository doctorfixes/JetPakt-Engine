"""Smoke-check: hard gates that must PASS before a draft can be staged or sent.

Applied to any .md draft produced by outreach_builder.py. Any failure
blocks the draft automatically.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .config import (
    SUBJECT_MAX_CHARS,
    BLOCKED_BODY_TOKENS,
    FORBIDDEN_TOKENS,
    REQUIRED_POSTAL,
)

EM_DASH = "\u2014"
EN_DASH = "\u2013"


@dataclass
class SmokeResult:
    path: Path
    subject: str
    body: str
    passes: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    legal_severity: str = ""  # populated when mapping is known

    @property
    def ok(self) -> bool:
        return not self.failures


def _split_draft(md_text: str) -> tuple[str, str]:
    lines = md_text.splitlines()
    subject = ""
    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line.split("SUBJECT:", 1)[1].strip()
            break
    dash_idxs = [i for i, l in enumerate(lines) if l.strip() == "---"]
    body = "\n".join(lines[dash_idxs[1] + 1 :]) if len(dash_idxs) >= 2 else md_text
    return subject, body


# Legal note required on LEGAL-HIGH drafts (service-charge / lawsuit context).
LEGAL_NOTE_MARKERS = ("hb25 1090", "hb25-1090", "hb 25-1090", "service-charge disclosure")


def check_draft(path: Path, legal_severity: str = "") -> SmokeResult:
    text = path.read_text(encoding="utf-8")
    subject, body = _split_draft(text)
    result = SmokeResult(path=path, subject=subject, body=body, legal_severity=legal_severity)

    def gate(name: str, cond: bool) -> None:
        (result.passes if cond else result.failures).append(name)

    gate("subject not empty", bool(subject))
    gate(f"subject <= {SUBJECT_MAX_CHARS} chars", len(subject) <= SUBJECT_MAX_CHARS)
    body_lower = body.lower()
    for tok in BLOCKED_BODY_TOKENS:
        gate(f"body excludes '{tok}'", tok not in body_lower)
    for tok in FORBIDDEN_TOKENS:
        gate(f"body excludes '{tok}'", tok not in body_lower)
    # em/en-dash only allowed on verbatim quote lines
    dashes_ok = all(
        (EM_DASH not in line and EN_DASH not in line) or line.startswith('    "')
        for line in body.splitlines()
    )
    gate("no em/en-dash in author copy", dashes_ok)
    gate("Parker postal address present", REQUIRED_POSTAL in body)
    gate("single Ryan signature block", body.count("Ryan B., JetPakt Solutions") == 1)
    gate("verbatim quote block present", '    "' in body)
    gate("no 'scrape' / 'crawl' language", "scrape" not in body_lower and "crawl" not in body_lower)
    gate("gojetpakt.com present", "gojetpakt.com" in body)

    if (legal_severity or "").upper() == "HIGH":
        has_note = any(m in body_lower for m in LEGAL_NOTE_MARKERS)
        gate("LEGAL-HIGH: legal note present", has_note)
    return result


def check_directory(dir_path: Path, legal_map: dict | None = None) -> List[SmokeResult]:
    """Smoke every .md draft in dir_path.

    legal_map: optional dict {business_name or slug: legal_severity}. When a
    draft matches by slug (file stem) or by business_name parsed from the
    header, its gate set includes the LEGAL-HIGH note gate.
    """
    out = []
    legal_map = legal_map or {}
    for p in sorted(dir_path.glob("*.md")):
        stem = p.stem
        # Derive business_name from header line "# Outreach draft — <name>"
        biz = ""
        try:
            first = p.read_text(encoding="utf-8").splitlines()[0]
            if first.startswith("# Outreach draft"):
                # Handle both em-dash and ASCII hyphen separators.
                for sep in (" \u2014 ", " - "):
                    if sep in first:
                        biz = first.split(sep, 1)[1].strip()
                        break
        except Exception:
            pass
        severity = legal_map.get(biz) or legal_map.get(stem) or ""
        out.append(check_draft(p, legal_severity=severity))
    return out
