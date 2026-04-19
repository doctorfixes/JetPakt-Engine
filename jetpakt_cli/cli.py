"""JetPakt single-command CLI.

Commands:
  jetpakt audit              Classify CRM rows into READY / DRAFTED / DISQUALIFIED.
  jetpakt smoke DIR          Run hard-gate checks on every draft in DIR.
  jetpakt draft              Generate drafts from a source JSON (outreach_builder).
  jetpakt prep-sync DIR      Emit sync_plan.json (Sheet updates + Log appends).
  jetpakt stage-outlook DIR  Emit outlook_plan.json (one Outlook action per draft).
  jetpakt plan DIR           Run smoke + prep-sync + stage-outlook (all plans).
  jetpakt wave DIR           Same as 'plan' then print a single-paste apply summary.
  jetpakt status             Inventory of waves and which plans exist.
  jetpakt full               audit + draft + smoke + prep-sync (one shot).

The CLI deliberately does NOT call external APIs (Outlook, Sheets) — those
are handled by the main agent via connectors, using the JSON artifacts this
CLI produces. That keeps the CLI deterministic, offline-testable, and cheap
to run on every change.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from . import config as cfg
from .smoke import check_directory, check_draft
from .sync import draft_to_log_row, now_iso
from .outlook import build_outlook_plan, write_outlook_plan


def _run_py(script: Path, *args: str) -> int:
    cmd = [sys.executable, str(script), *args]
    return subprocess.call(cmd, cwd=str(cfg.REPO_ROOT))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_audit(_args: argparse.Namespace) -> int:
    return _run_py(cfg.REPO_ROOT / "crm_audit.py")


def _resolve_dir(directory: str) -> Path:
    p = Path(directory)
    if not p.is_absolute():
        p = cfg.REPO_ROOT / p
    return p


def _load_mapping(path: str) -> Dict[str, dict]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_absolute():
        p = cfg.REPO_ROOT / p
    return json.loads(p.read_text()) if p.exists() else {}


def _legal_map(mapping: Dict[str, dict]) -> Dict[str, str]:
    """Produce {business_name: legal_severity} from mapping for smoke gates."""
    out = {}
    for key, m in mapping.items():
        sev = (m or {}).get("legal_severity", "") or (m or {}).get("legal_flag_severity", "")
        if sev:
            out[key] = sev
    return out


def cmd_smoke(args: argparse.Namespace) -> int:
    dir_path = _resolve_dir(args.directory)
    if not dir_path.exists():
        print(f"ERROR: directory not found: {dir_path}")
        return 2
    mapping = _load_mapping(getattr(args, "mapping", ""))
    results = check_directory(dir_path, legal_map=_legal_map(mapping))
    if not results:
        print(f"No .md drafts in {dir_path}")
        return 0

    failing = 0
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        sev = f" [legal={r.legal_severity}]" if r.legal_severity else ""
        print(f"[{status}] {r.path.name}  subject: {r.subject!r}  ({len(r.subject)}c){sev}")
        for f in r.failures:
            print(f"    FAIL: {f}")
            failing += 1
    print(f"\n{len(results)} drafts, {failing} gate failures.")
    return 0 if failing == 0 else 1


def cmd_draft(args: argparse.Namespace) -> int:
    script = cfg.REPO_ROOT / "outreach_builder.py"
    cmd_args = [
        "--top", str(args.top),
        "--source", args.source,
        "--out", args.out,
        "--wave-name", args.wave_name,
    ]
    return _run_py(script, *cmd_args)


def cmd_prep_sync(args: argparse.Namespace) -> int:
    """Build a sync plan file the main agent can execute via the Sheets connector.

    The plan lists (a) prospect stage updates, (b) outreach-log row appends.
    The main agent applies this by calling the connector with each payload.
    """
    dir_path = _resolve_dir(args.directory)
    manifest_path = dir_path / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found in {dir_path}")
        return 2

    manifest = json.loads(manifest_path.read_text())
    mapping = _load_mapping(args.mapping)

    results = check_directory(dir_path, legal_map=_legal_map(mapping))
    fail = [r for r in results if not r.ok]
    if fail:
        print("Smoke-check failures block sync. Fix these first:")
        for r in fail:
            print(f"  {r.path.name}: {r.failures}")
        return 1

    plan = {
        "generated_at": now_iso(),
        "sheet_id": cfg.SHEET_ID,
        "sheet_url": cfg.SHEET_URL,
        "worksheet_ids": cfg.WORKSHEET_IDS,
        "wave_name": manifest.get("wave_name"),
        "prospect_updates": [],
        "outreach_log_appends": [],
    }

    for d in manifest.get("drafts", []):
        biz = d["business_name"]
        slug = d["source_row_key"]
        mapped = mapping.get(biz) or mapping.get(slug) or {}
        prospect_id = mapped.get("prospect_id") or slug
        pillar = mapped.get("pillar", "")
        case_id = mapped.get("case_id", "")
        next_action = mapped.get("next_action_due", "")
        draft_path = dir_path / f"{slug}.md"
        if not draft_path.exists():
            print(f"WARN: draft file missing for {biz}: {draft_path}")
            continue
        tag = f"{manifest.get('wave_name', 'wave')}_{slug[:12]}"
        log_row = draft_to_log_row(prospect_id, draft_path, pillar=pillar, case_id=case_id, tag=tag)
        plan["outreach_log_appends"].append({
            "spreadsheetId": cfg.SHEET_ID,
            "worksheetId": cfg.WORKSHEET_IDS["Outreach Log"],
            "row_object": {
                "log_id": log_row.log_id,
                "prospect_id": prospect_id,
                "direction": log_row.direction,
                "channel": log_row.channel,
                "touch_type": log_row.touch_type,
                "template_version": log_row.template_version,
                "subject": log_row.subject,
                "body_excerpt": log_row.body_excerpt,
                "draft_file": log_row.draft_file,
                "pillar": pillar,
                "case_id": case_id,
                "sent_at": "",
                "reply_received_at": "",
                "reply_sentiment": "",
                "result": "drafted",
                "created_at": log_row.created_at,
            },
        })
        plan["prospect_updates"].append({
            "spreadsheetId": cfg.SHEET_ID,
            "worksheetId": cfg.WORKSHEET_IDS["Prospects"],
            "find": {"column": "A", "value": prospect_id},
            "set": {
                "stage": "Drafted",
                "stage_entered_at": log_row.created_at,
                "next_action_due": next_action,
                "updated_at": log_row.created_at,
                "notes_append": f"Draft generated {log_row.created_at[:10]} via {manifest.get('wave_name')}; subject: {log_row.subject}",
            },
        })

    out_path = dir_path / "sync_plan.json"
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote sync plan with {len(plan['prospect_updates'])} prospect update(s) and "
          f"{len(plan['outreach_log_appends'])} log append(s):")
    print(f"  {out_path}")
    return 0


def cmd_stage_outlook(args: argparse.Namespace) -> int:
    """Build outlook_plan.json the main agent applies via outlook.draft_email."""
    dir_path = _resolve_dir(args.directory)
    manifest_path = dir_path / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found in {dir_path}")
        return 2
    manifest = json.loads(manifest_path.read_text())
    mapping = _load_mapping(args.mapping)

    # Gate drafts before staging.
    results = check_directory(dir_path, legal_map=_legal_map(mapping))
    fail = [r for r in results if not r.ok]
    if fail and not args.force:
        print("Smoke-check failures block Outlook staging. Fix these first or pass --force:")
        for r in fail:
            print(f"  {r.path.name}: {r.failures}")
        return 1

    plan = build_outlook_plan(dir_path, manifest, mapping)
    out = write_outlook_plan(dir_path, plan)
    s = plan["summary"]
    print(
        f"Wrote outlook plan: {s['total']} action(s) — draft_email={s['draft_email']}, "
        f"skip_no_email={s['skip_no_email']}, skip_missing_file={s['skip_missing_file']}"
    )
    print(f"  {out}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Emit every plan file a wave needs in one call: sync_plan + outlook_plan."""
    rc = cmd_smoke(args)
    if rc != 0:
        return rc
    rc = cmd_prep_sync(args)
    if rc != 0:
        return rc
    return cmd_stage_outlook(args)


def cmd_wave(args: argparse.Namespace) -> int:
    """Run 'plan' and then print a copy-paste apply summary for the agent."""
    rc = cmd_plan(args)
    if rc != 0:
        return rc
    dir_path = _resolve_dir(args.directory)
    sync = dir_path / "sync_plan.json"
    outlook = dir_path / "outlook_plan.json"
    print("\n=== WAVE READY TO APPLY ===")
    print(f"Sheet: {cfg.SHEET_URL}")
    if sync.exists():
        d = json.loads(sync.read_text())
        print(f"Sheet actions: {len(d['prospect_updates'])} Prospects update(s), "
              f"{len(d['outreach_log_appends'])} Log append(s)")
    if outlook.exists():
        d = json.loads(outlook.read_text())
        s = d["summary"]
        print(f"Outlook actions: {s['draft_email']} draft_email, "
              f"{s['skip_no_email']} skipped (no email), "
              f"{s['skip_missing_file']} skipped (missing file)")
    print("\nNext: agent reads both plan files and applies via connectors.")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    # Minimal status: count drafts by wave directory.
    root = cfg.DRAFTS_DIR
    if not root.exists():
        print("No drafts directory.")
        return 0
    waves = sorted([p for p in root.iterdir() if p.is_dir()])
    print(f"JetPakt status — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"Sheet: {cfg.SHEET_URL}")
    print(f"Drafts root: {root}")
    for w in waves:
        mds = list(w.glob("*.md"))
        tags = []
        if (w / "sync_plan.json").exists():
            tags.append("sync")
        if (w / "outlook_plan.json").exists():
            tags.append("outlook")
        tag = f"  [{'+'.join(tags)}]" if tags else ""
        print(f"  - {w.name}: {len(mds)} draft(s){tag}")
    return 0


def cmd_full(args: argparse.Namespace) -> int:
    print("=== audit ===")
    rc = cmd_audit(args)
    if rc != 0:
        return rc
    if args.source and args.out:
        print("\n=== draft ===")
        rc = cmd_draft(args)
        if rc != 0:
            return rc
        print("\n=== smoke ===")
        args.directory = args.out
        rc = cmd_smoke(args)
        if rc != 0:
            return rc
        print("\n=== prep-sync ===")
        args.mapping = args.mapping
        rc = cmd_prep_sync(args)
        if rc != 0:
            return rc
    print("\n=== status ===")
    return cmd_status(args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(prog="jetpakt", description="JetPakt ops CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("audit").set_defaults(func=cmd_audit)

    smoke = sub.add_parser("smoke")
    smoke.add_argument("directory")
    smoke.add_argument("--mapping", default="")
    smoke.set_defaults(func=cmd_smoke)

    draft = sub.add_parser("draft")
    draft.add_argument("--top", type=int, default=5)
    draft.add_argument("--source", required=True)
    draft.add_argument("--out", required=True)
    draft.add_argument("--wave-name", required=True)
    draft.set_defaults(func=cmd_draft)

    prep = sub.add_parser("prep-sync")
    prep.add_argument("directory")
    prep.add_argument("--mapping", default="")
    prep.set_defaults(func=cmd_prep_sync)

    stage = sub.add_parser("stage-outlook")
    stage.add_argument("directory")
    stage.add_argument("--mapping", default="")
    stage.add_argument("--force", action="store_true", help="Skip smoke gates")
    stage.set_defaults(func=cmd_stage_outlook)

    plan = sub.add_parser("plan")
    plan.add_argument("directory")
    plan.add_argument("--mapping", default="")
    plan.add_argument("--force", action="store_true")
    plan.set_defaults(func=cmd_plan)

    wave = sub.add_parser("wave")
    wave.add_argument("directory")
    wave.add_argument("--mapping", default="")
    wave.add_argument("--force", action="store_true")
    wave.set_defaults(func=cmd_wave)

    sub.add_parser("status").set_defaults(func=cmd_status)

    full = sub.add_parser("full")
    full.add_argument("--source", default="")
    full.add_argument("--out", default="")
    full.add_argument("--wave-name", default="")
    full.add_argument("--top", type=int, default=5)
    full.add_argument("--mapping", default="")
    full.set_defaults(func=cmd_full)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
