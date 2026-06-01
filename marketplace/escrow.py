"""Escrow phase — Stripe payment held until verification passes."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Transaction, TransactionStatus, VerificationResult
from .post import get_post
from .state_machine import transition
from stripe.escrow import hold_payment, release_payment


_transactions: dict[str, Transaction] = {}


def create_transaction(
    post_id: str,
    bookkeeper_id: str,
    accepted_bid_id: str,
    price_cents: int,
    stripe_payment_intent_id: str | None = None,
) -> Transaction:
    """Create a transaction and hold funds in escrow."""
    tx = Transaction(
        post_id=post_id,
        bookkeeper_id=bookkeeper_id,
        accepted_bid_id=accepted_bid_id,
        price_cents=price_cents,
        status=TransactionStatus.IN_ESCROW,
        stripe_payment_intent_id=stripe_payment_intent_id,
    )
    _transactions[tx.tx_id] = tx
    return tx


def get_transaction(tx_id: str) -> Transaction | None:
    return _transactions.get(tx_id)


def list_transactions(status: TransactionStatus | None = None) -> list[Transaction]:
    if status:
        return [t for t in _transactions.values() if t.status == status]
    return list(_transactions.values())


def start_execution(tx_id: str) -> Transaction:
    """Advance from escrow → executing."""
    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")
    tx.status = transition(tx.status, TransactionStatus.EXECUTING)
    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx


def submit_for_verification(tx_id: str, verification_report: dict) -> Transaction:
    """Bookkeeper submits completed work. Advance to verifying."""
    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")
    tx.status = transition(tx.status, TransactionStatus.VERIFYING)
    tx.verification_report = verification_report
    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx


def record_verification_result(tx_id: str, result: VerificationResult) -> Transaction:
    """Record verification outcome and advance accordingly."""
    from .state_machine import transition_on_verify

    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")

    next_status = transition_on_verify(result)
    tx.status = transition(tx.status, next_status)
    tx.verification_result = result

    if result == VerificationResult.PASS:
        tx.escrow_released_at = datetime.now(timezone.utc).isoformat()

    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx


def settle(tx_id: str) -> Transaction:
    """Release payment from escrow and finalize."""
    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")

    tx.status = transition(tx.status, TransactionStatus.SETTLED)
    tx.settled_at = datetime.now(timezone.utc).isoformat()
    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx


def dispute(tx_id: str) -> Transaction:
    """Flag a transaction as disputed."""
    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")
    tx.status = transition(tx.status, TransactionStatus.DISPUTED)
    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx


def cancel(tx_id: str) -> Transaction:
    """Cancel a transaction before settlement."""
    tx = get_transaction(tx_id)
    if not tx:
        raise ValueError(f"Transaction not found: {tx_id}")
    tx.status = transition(tx.status, TransactionStatus.CANCELLED)
    tx.updated_at = datetime.now(timezone.utc).isoformat()
    _transactions[tx_id] = tx
    return tx