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
from .inbox import (
    Prospect, Hit, build_query_plan, classify_hit,
    build_apply_plan, load_prospects_from_json, prospects_by_domain,
)
from .clients import (
    load_stripe_customer, load_stripe_subscription, load_prospects,
    build_onboarding_plan,
)
from .enrich import (
    load_prospects_full, build_refresh_plan, build_enrich_plan,
)


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


def cmd_inbox_plan(args: argparse.Namespace) -> int:
    """Emit inbox_query_plan.json from a prospects JSON file.

    The prospects JSON is a list of {prospect_id, business_name, owner_email,
    stage, legal_severity} objects. The agent sources this from the Prospects
    tab (or provides a test fixture).
    """
    prospects_path = Path(args.prospects)
    if not prospects_path.is_absolute():
        prospects_path = cfg.REPO_ROOT / prospects_path
    if not prospects_path.exists():
        print(f"ERROR: prospects JSON not found: {prospects_path}")
        return 2
    prospects = load_prospects_from_json(prospects_path)
    plan = build_query_plan(prospects, lookback_days=args.lookback_days)
    out_path = Path(args.out) if args.out else (prospects_path.parent / "inbox_query_plan.json")
    if not out_path.is_absolute():
        out_path = cfg.REPO_ROOT / out_path
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote query plan: {len(plan['queries'])} query(ies), "
          f"{plan['domain_count']} domain(s) across {plan['prospect_count']} prospect(s)")
    print(f"  {out_path}")
    return 0


def cmd_inbox_apply(args: argparse.Namespace) -> int:
    """Read a hits JSON (produced by the agent from search_email results),
    classify each hit, and emit inbox_apply_plan.json with Sheet actions.
    """
    prospects_path = Path(args.prospects)
    if not prospects_path.is_absolute():
        prospects_path = cfg.REPO_ROOT / prospects_path
    hits_path = Path(args.hits)
    if not hits_path.is_absolute():
        hits_path = cfg.REPO_ROOT / hits_path
    if not prospects_path.exists():
        print(f"ERROR: prospects JSON not found: {prospects_path}")
        return 2
    if not hits_path.exists():
        print(f"ERROR: hits JSON not found: {hits_path}")
        return 2

    prospects = load_prospects_from_json(prospects_path)
    by_domain = prospects_by_domain(prospects)

    hits_raw = json.loads(hits_path.read_text(encoding="utf-8"))
    classifications = []
    for h in hits_raw:
        hit = Hit(
            message_id=h.get("message_id", ""),
            from_email=h.get("from_email", ""),
            from_name=h.get("from_name", ""),
            subject=h.get("subject", ""),
            received_at=h.get("received_at", ""),
            body_preview=h.get("body_preview", ""),
            to_list=h.get("to_list", []) or [],
        )
        classifications.append(classify_hit(hit, by_domain))

    plan = build_apply_plan(classifications)
    out_path = Path(args.out) if args.out else (hits_path.parent / "inbox_apply_plan.json")
    if not out_path.is_absolute():
        out_path = cfg.REPO_ROOT / out_path
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    s = plan["summary"]
    print(f"Wrote apply plan: replies={s['replies']}, unsubscribes={s['unsubscribes']}, "
          f"bounces={s['bounces']}, ignored={s['ignored']}")
    print(f"  Prospect updates: {len(plan['prospect_updates'])}")
    print(f"  Outreach Log appends: {len(plan['outreach_log_appends'])}")
    print(f"  Suppression appends: {len(plan['suppression_appends'])}")
    print(f"  {out_path}")
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    """Build an onboarding plan from a Stripe customer + subscription JSON.

    Emits onboarding_plan.json with clients_append, prospect_updates, and a
    welcome email draft. The agent applies via google_sheets + outlook.
    """
    customer_path = Path(args.customer)
    if not customer_path.is_absolute():
        customer_path = cfg.REPO_ROOT / customer_path
    prospects_path = Path(args.prospects)
    if not prospects_path.is_absolute():
        prospects_path = cfg.REPO_ROOT / prospects_path
    sub_path = None
    if args.subscription:
        sub_path = Path(args.subscription)
        if not sub_path.is_absolute():
            sub_path = cfg.REPO_ROOT / sub_path

    for p in (customer_path, prospects_path):
        if not p.exists():
            print(f"ERROR: missing file: {p}")
            return 2

    customer = load_stripe_customer(customer_path)
    subscription = load_stripe_subscription(sub_path)
    prospects = load_prospects(prospects_path)

    plan = build_onboarding_plan(customer, subscription, prospects)

    out_path = Path(args.out) if args.out else (customer_path.parent / "onboarding_plan.json")
    if not out_path.is_absolute():
        out_path = cfg.REPO_ROOT / out_path
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    s = plan["summary"]
    print(f"Onboarded: client_id={s['client_id']} prospect_id={s['prospect_id']}")
    print(f"  tier={s['tier']} cadence={s['cadence']} mrr=${s['mrr_usd']}")
    print(f"  matched_prospect={s['matched_prospect']} next_due={s['next_deliverable_due']}")
    print(f"  Clients append: 1")
    print(f"  Prospect updates: {len(plan['prospect_updates'])}")
    print(f"  Outlook drafts: {len(plan['outlook_drafts'])}")
    print(f"  {out_path}")
    return 0


def cmd_refresh_ratings(args: argparse.Namespace) -> int:
    """Diff stored ratings against live Places API hits."""
    prospects_path = Path(args.prospects)
    hits_path = Path(args.hits)
    if not prospects_path.is_absolute():
        prospects_path = cfg.REPO_ROOT / prospects_path
    if not hits_path.is_absolute():
        hits_path = cfg.REPO_ROOT / hits_path
    for p in (prospects_path, hits_path):
        if not p.exists():
            print(f"ERROR: missing file: {p}")
            return 2

    prospects = load_prospects_full(prospects_path)
    hits = json.loads(hits_path.read_text(encoding="utf-8"))
    plan = build_refresh_plan(prospects, hits)

    out_path = Path(args.out) if args.out else (hits_path.parent / "refresh_plan.json")
    if not out_path.is_absolute():
        out_path = cfg.REPO_ROOT / out_path
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    s = plan["summary"]
    print(f"Refresh plan: hits={s['hits_checked']}, updates={s['updates']}, "
          f"skipped_no_drift={s['skipped_no_drift']}, unmatched={s['unmatched']}")
    print(f"  Thresholds: rating>={s['rating_drift_min']}, "
          f"reviews>={s['review_count_drift_min']}")
    print(f"  {out_path}")
    return 0


def cmd_enrich_emails(args: argparse.Namespace) -> int:
    """Fill in missing owner_email from Hunter high-confidence hits."""
    prospects_path = Path(args.prospects)
    hits_path = Path(args.hits)
    if not prospects_path.is_absolute():
        prospects_path = cfg.REPO_ROOT / prospects_path
    if not hits_path.is_absolute():
        hits_path = cfg.REPO_ROOT / hits_path
    for p in (prospects_path, hits_path):
        if not p.exists():
            print(f"ERROR: missing file: {p}")
            return 2

    prospects = load_prospects_full(prospects_path)
    hits = json.loads(hits_path.read_text(encoding="utf-8"))
    plan = build_enrich_plan(prospects, hits, missing_only=not args.all)

    out_path = Path(args.out) if args.out else (hits_path.parent / "enrich_plan.json")
    if not out_path.is_absolute():
        out_path = cfg.REPO_ROOT / out_path
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    s = plan["summary"]
    print(f"Enrich plan: hunter_hits={s['hunter_hits']}, passing_conf={s['passing_confidence_floor']}, "
          f"updates={s['updates']}, skipped={s['skipped']}")
    print(f"  Confidence floor: {s['confidence_floor']}, missing_only={s['missing_only']}")
    print(f"  {out_path}")
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

    ibp = sub.add_parser("inbox-plan", help="Emit inbox_query_plan.json from prospects JSON")
    ibp.add_argument("--prospects", required=True,
                     help="Path to JSON list of prospect records")
    ibp.add_argument("--out", default="",
                     help="Output path (defaults to inbox_query_plan.json next to prospects)")
    ibp.add_argument("--lookback-days", type=int, default=3)
    ibp.set_defaults(func=cmd_inbox_plan)

    iba = sub.add_parser("inbox-apply", help="Classify hits JSON + emit inbox_apply_plan.json")
    iba.add_argument("--prospects", required=True)
    iba.add_argument("--hits", required=True,
                     help="Path to JSON list of normalized Outlook hits")
    iba.add_argument("--out", default="")
    iba.set_defaults(func=cmd_inbox_apply)

    ob = sub.add_parser("onboard", help="Onboard a Stripe customer into a Clients row + welcome draft")
    ob.add_argument("--customer", required=True, help="Path to stripe_customer.json")
    ob.add_argument("--subscription", default="",
                    help="Path to stripe_subscription.json (omit for Scan one-time)")
    ob.add_argument("--prospects", required=True, help="Path to prospects.json")
    ob.add_argument("--out", default="")
    ob.set_defaults(func=cmd_onboard)

    rr = sub.add_parser("refresh-ratings", help="Diff stored vs live ratings")
    rr.add_argument("--prospects", required=True, help="Path to prospects_full.json (26-col)")
    rr.add_argument("--hits", required=True, help="Path to places_hits.json")
    rr.add_argument("--out", default="")
    rr.set_defaults(func=cmd_refresh_ratings)

    ee = sub.add_parser("enrich-emails", help="Fill owner_email from Hunter hits")
    ee.add_argument("--prospects", required=True, help="Path to prospects_full.json (26-col)")
    ee.add_argument("--hits", required=True, help="Path to hunter_hits.json")
    ee.add_argument("--all", action="store_true",
                    help="Also consider rows that already have an email (never overwrites)")
    ee.add_argument("--out", default="")
    ee.set_defaults(func=cmd_enrich_emails)

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
