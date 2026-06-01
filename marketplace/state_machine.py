"""Marketplace state machine — enforces valid Post→Bid→Escrow→Execute→Verify→Settle flow."""

from __future__ import annotations

from .models import TransactionStatus, VerificationResult


# ── Allowed transitions ────────────────────────────────────────────────────────

_TRANSITIONS: dict[TransactionStatus, set[TransactionStatus]] = {
    TransactionStatus.POSTED: {TransactionStatus.BIDDING, TransactionStatus.CANCELLED},
    TransactionStatus.BIDDING: {TransactionStatus.BIDDING_CLOSED, TransactionStatus.CANCELLED},
    TransactionStatus.BIDDING_CLOSED: {TransactionStatus.IN_ESCROW, TransactionStatus.CANCELLED},
    TransactionStatus.IN_ESCROW: {TransactionStatus.EXECUTING, TransactionStatus.CANCELLED, TransactionStatus.DISPUTED},
    TransactionStatus.EXECUTING: {TransactionStatus.VERIFYING, TransactionStatus.DISPUTED},
    TransactionStatus.VERIFYING: {TransactionStatus.VERIFIED, TransactionStatus.DISPUTED},
    TransactionStatus.VERIFIED: {TransactionStatus.SETTLED, TransactionStatus.DISPUTED},
    TransactionStatus.SETTLED: set(),  # Terminal
    TransactionStatus.DISPUTED: {TransactionStatus.VERIFIED, TransactionStatus.CANCELLED},  # Re-verify possible
    TransactionStatus.CANCELLED: set(),  # Terminal
}

# Verification results map to next status
_VERIFICATION_MAP = {
    VerificationResult.PASS: TransactionStatus.VERIFIED,
    VerificationResult.FAIL: TransactionStatus.DISPUTED,
}


def can_transition(from_status: TransactionStatus, to_status: TransactionStatus) -> bool:
    """Check if moving from → to is a valid lifecycle transition."""
    allowed = _TRANSITIONS.get(from_status, set())
    return to_status in allowed


def transition(from_status: TransactionStatus, to_status: TransactionStatus) -> TransactionStatus:
    """Transition or raise."""
    if not can_transition(from_status, to_status):
        raise ValueError(
            f"Cannot transition from {from_status.value} → {to_status.value}. "
            f"Allowed: {[s.value for s in _TRANSITIONS.get(from_status, set())]}"
        )
    return to_status


def transition_on_verify(result: VerificationResult) -> TransactionStatus:
    """Map a verification result to the next transaction status."""
    status = _VERIFICATION_MAP.get(result)
    if status is None:
        raise ValueError(f"Unknown verification result: {result}")
    return status


def terminal_statuses() -> list[str]:
    """Return statuses that are terminal (no further transitions possible)."""
    return [
        s.value for s, next_set in _TRANSITIONS.items()
        if not next_set
    ]


def active_statuses() -> list[str]:
    """Return statuses that represent in-flight transactions."""
    terminals = set(terminal_statuses())
    return [
        s.value for s in TransactionStatus
        if s.value not in terminals
    ]


def requires_owner_action(status: TransactionStatus) -> bool:
    """True if this status needs something from the business owner."""
    return status in {
        TransactionStatus.POSTED,
        TransactionStatus.BIDDING_CLOSED,
        TransactionStatus.DISPUTED,
    }


def requires_bookkeeper_action(status: TransactionStatus) -> bool:
    """True if this status needs something from the bookkeeper."""
    return status in {
        TransactionStatus.BIDDING,
        TransactionStatus.EXECUTING,
    }


# ── Status descriptions (for UI rendering) ─────────────────────────────────────

STATUS_DESCRIPTIONS = {
    TransactionStatus.POSTED: "Submitted for review. Waiting for bookkeepers.",
    TransactionStatus.BIDDING: "Bookkeepers are reviewing and placing bids.",
    TransactionStatus.BIDDING_CLOSED: "Bidding closed. Owner selects a bookkeeper.",
    TransactionStatus.IN_ESCROW: "Payment held securely. Bookkeeper can start work.",
    TransactionStatus.EXECUTING: "Bookkeeper is reconciling the accounts.",
    TransactionStatus.VERIFYING: "Running automated verification checks.",
    TransactionStatus.VERIFIED: "Accounts verified. Ready to release payment.",
    TransactionStatus.SETTLED: "Payment released. Transaction complete.",
    TransactionStatus.DISPUTED: "Verification failed. Escalation in progress.",
    TransactionStatus.CANCELLED: "Transaction cancelled.",
}
