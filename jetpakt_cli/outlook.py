"""Stage-outlook planner.

Reads a wave directory of .md drafts + a mapping.json and emits
outlook_plan.json. The main agent applies each action via the
outlook.draft_email connector call.

Plan format:
{
  "generated_at": "...",
  "wave_name": "...",
  "actions": [
    {
      "action": "draft_email",
      "connector": "outlook",
      "tool": "draft_email",
      "arguments": {
        "to": ["info@..."],
        "cc": [],
        "bcc": [],
        "subject": "...",
        "body": "...plain text..."
      },
      "prospect_id": "arvada_...",
      "draft_file": "/abs/path/to/draft.md",
      "idempotency_key": "outlook_draft::<prospect_id>::<subject_hash8>"
    }
  ]
}
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .sync import now_iso


@dataclass
class ParsedDraft:
    subject: str
    body: str


def parse_draft(md_path: Path) -> ParsedDraft:
    """Extract SUBJECT + plain-text body from a draft .md file."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    subject = ""
    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line.split("SUBJECT:", 1)[1].strip()
            break
    dash_idxs = [i for i, l in enumerate(lines) if l.strip() == "---"]
    body = "\n".join(lines[dash_idxs[1] + 1 :]).strip() if len(dash_idxs) >= 2 else text
    return ParsedDraft(subject=subject, body=body)


def idempotency_key(prospect_id: str, subject: str) -> str:
    h = hashlib.sha1(subject.encode("utf-8")).hexdigest()[:8]
    return f"outlook_draft::{prospect_id}::{h}"


def build_outlook_plan(
    wave_dir: Path,
    manifest: dict,
    mapping: Dict[str, dict],
) -> dict:
    """Build outlook_plan.json contents for every draft in the wave."""
    actions: List[dict] = []
    for d in manifest.get("drafts", []):
        biz = d["business_name"]
        slug = d["source_row_key"]
        mapped = mapping.get(biz) or mapping.get(slug) or {}
        to_email = mapped.get("email") or d.get("email")
        if not to_email:
            # Skip drafts with no email — still write a placeholder action for visibility.
            actions.append({
                "action": "skip_no_email",
                "reason": "no email in mapping or manifest",
                "business_name": biz,
                "prospect_id": mapped.get("prospect_id", slug),
                "draft_file": str(wave_dir / f"{slug}.md"),
            })
            continue
        draft_path = wave_dir / f"{slug}.md"
        if not draft_path.exists():
            actions.append({
                "action": "skip_missing_file",
                "reason": f"draft file not found: {draft_path.name}",
                "business_name": biz,
                "prospect_id": mapped.get("prospect_id", slug),
                "draft_file": str(draft_path),
            })
            continue
        parsed = parse_draft(draft_path)
        prospect_id = mapped.get("prospect_id", slug)
        actions.append({
            "action": "draft_email",
            "connector": "outlook",
            "tool": "draft_email",
            "arguments": {
                "to": [to_email],
                "cc": [],
                "bcc": [],
                "subject": parsed.subject,
                "body": parsed.body,
            },
            "prospect_id": prospect_id,
            "business_name": biz,
            "draft_file": str(draft_path),
            "idempotency_key": idempotency_key(prospect_id, parsed.subject),
        })

    return {
        "generated_at": now_iso(),
        "wave_name": manifest.get("wave_name"),
        "wave_dir": str(wave_dir),
        "summary": {
            "total": len(actions),
            "draft_email": sum(1 for a in actions if a["action"] == "draft_email"),
            "skip_no_email": sum(1 for a in actions if a["action"] == "skip_no_email"),
            "skip_missing_file": sum(1 for a in actions if a["action"] == "skip_missing_file"),
        },
        "actions": actions,
    }


def write_outlook_plan(wave_dir: Path, plan: dict) -> Path:
    out_path = wave_dir / "outlook_plan.json"
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
