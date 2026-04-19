"""Configuration for the JetPakt CLI.

All IDs, paths, and defaults live here so the rest of the CLI can stay simple.
"""
from pathlib import Path

# --- Paths ------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
DRAFTS_DIR = OUTPUT_DIR / "outreach"
ARCHIVE_DIR = REPO_ROOT / "archive"
WIDE_DIR = REPO_ROOT.parent / "wide"

CRM_CSV = OUTPUT_DIR / "denver_restaurant_leads_full_audit.csv"
READY_QUEUE = OUTPUT_DIR / "crm_ready_queue.json"

# --- Google Sheets (JetPakt CRM Master) -------------------------------------
SHEET_ID = "1L2NqIcZeG_SMqoL_L3YN_IlqiVkMWy4SyBsu2Sa07yI"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

# Worksheet IDs (integers, from google_sheets-get-spreadsheet-info)
WORKSHEET_IDS = {
    "Prospects": 2139708364,
    "ICP Targets": 1559684998,
    "Outreach Log": 250333527,
    "Metrics": 1953076964,
    "Pipeline": 1925316065,
    "Suppression": 1712783155,
}

# --- Inbox-scan defaults ----------------------------------------------------
# Bounce signal phrases used by Microsoft Exchange / Outlook postmasters.
BOUNCE_SUBJECT_TOKENS = (
    "undeliverable", "undelivered", "delivery status notification",
    "mail delivery failed", "returned mail", "delivery has failed",
    "message not delivered",
)
BOUNCE_FROM_TOKENS = (
    "mailer-daemon", "postmaster", "mail delivery subsystem",
    "mailer_daemon", "no-reply-delivery",
)
# Phrases that indicate an opt-out / unsubscribe intent in the reply body.
UNSUB_TOKENS = (
    "unsubscribe", "take me off", "remove me", "stop emailing",
    "do not email", "don't email me", "stop contacting",
    "not interested", "please remove",
)

# --- Outreach policy --------------------------------------------------------
TEMPLATE_VERSION = "v3-drift-personalized"
DEFAULT_CHANNEL = "outlook"
DEFAULT_TOUCH_TYPE = "cold_drift"
ROUTING = "ryan_drafts"

# --- Smoke-check gates ------------------------------------------------------
SUBJECT_MAX_CHARS = 45
BLOCKED_BODY_TOKENS = ("denver",)
FORBIDDEN_TOKENS = ("food poisoning", "made me sick", "hospital", "salmonella",
                    "e. coli", "norovirus", "got sick")
REQUIRED_POSTAL = "6222 E Pine Lane, Suite 6212, Parker, CO 80138"
