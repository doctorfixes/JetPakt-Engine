"""Marketplace API routes — Post → Bid → Escrow → Execute → Verify → Settle."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from marketplace.bid import accept_bid as _accept_bid
from marketplace.bid import get_bid as _get_bid
from marketplace.bid import list_bids, place_bid, withdraw_bid
from marketplace.escrow import (
    cancel as _cancel_tx,
    create_transaction,
    dispute as _dispute_tx,
    get_transaction,
    list_transactions,
    record_verification_result,
    settle as _settle_tx,
    start_execution,
    submit_for_verification,
)
from marketplace.models import Bookkeeper, BookkeeperTier, BusinessOwner, TransactionStatus, VerificationResult
from marketplace.post import create_post, delete_post, get_post, list_posts
from verification.engine import LedgerData, verify

router = APIRouter(prefix="/api")


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "service": "jetpakt-marketplace"}


# ── Posts ──────────────────────────────────────────────────────────────────────

@router.post("/posts")
async def api_create_post(
    owner_id: str,
    business_name: str,
    period_end: str,
    deadline: str,
    budget_cents: int,
    description: str,
    chart_of_accounts: str | None = None,
    bank_statements: list[str] | None = None,
):
    post = create_post(
        owner_id=owner_id,
        business_name=business_name,
        period_end=period_end,
        deadline=deadline,
        budget_cents=budget_cents,
        description=description,
        chart_of_accounts=chart_of_accounts,
        bank_statements=bank_statements,
    )
    return {"post": post.to_dict(), "status": "created"}


@router.get("/posts")
async def api_list_posts(status: str | None = None):
    status_filter = TransactionStatus(status) if status else None
    return {"posts": [p.to_dict() for p in list_posts(status_filter)]}


@router.get("/posts/{post_id}")
async def api_get_post(post_id: str):
    post = get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"post": post.to_dict()}


@router.delete("/posts/{post_id}")
async def api_delete_post(post_id: str):
    deleted = delete_post(post_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"status": "deleted", "post_id": post_id}


# ── Bids ───────────────────────────────────────────────────────────────────────

@router.post("/posts/{post_id}/bids")
async def api_place_bid(
    post_id: str,
    bookkeeper_id: str,
    price_cents: int,
    turnaround_days: int,
    cover_note: str = "",
):
    bid = place_bid(
        post_id=post_id,
        bookkeeper_id=bookkeeper_id,
        price_cents=price_cents,
        turnaround_days=turnaround_days,
        cover_note=cover_note,
    )
    return {"bid": bid.to_dict(), "status": "placed"}


@router.get("/posts/{post_id}/bids")
async def api_list_bids(post_id: str):
    return {"bids": [b.to_dict() for b in list_bids(post_id)]}


@router.post("/bids/{bid_id}/accept")
async def api_accept_bid(bid_id: str):
    bid = _accept_bid(bid_id)
    return {"bid": bid.to_dict(), "status": "accepted"}


@router.post("/bids/{bid_id}/withdraw")
async def api_withdraw_bid(bid_id: str):
    bid = withdraw_bid(bid_id)
    return {"bid": bid.to_dict(), "status": "withdrawn"}


# ── Escrow / Transactions ──────────────────────────────────────────────────────

@router.post("/transactions")
async def api_create_transaction(
    post_id: str,
    bookkeeper_id: str,
    accepted_bid_id: str,
    price_cents: int,
    stripe_payment_intent_id: str | None = None,
):
    tx = create_transaction(
        post_id=post_id,
        bookkeeper_id=bookkeeper_id,
        accepted_bid_id=accepted_bid_id,
        price_cents=price_cents,
        stripe_payment_intent_id=stripe_payment_intent_id,
    )
    return {"transaction": tx.to_dict(), "status": "created"}


@router.get("/transactions")
async def api_list_transactions(status: str | None = None):
    status_filter = TransactionStatus(status) if status else None
    return {"transactions": [t.to_dict() for t in list_transactions(status_filter)]}


@router.get("/transactions/{tx_id}")
async def api_get_transaction(tx_id: str):
    tx = get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"transaction": tx.to_dict()}


@router.post("/transactions/{tx_id}/execute")
async def api_start_execution(tx_id: str):
    tx = start_execution(tx_id)
    return {"transaction": tx.to_dict(), "status": "executing"}


@router.post("/transactions/{tx_id}/verify-submit")
async def api_submit_for_verification(tx_id: str, report: dict):
    tx = submit_for_verification(tx_id, report)
    return {"transaction": tx.to_dict(), "status": "verifying"}


@router.post("/transactions/{tx_id}/verify-result")
async def api_record_verification(tx_id: str, result: str, ledger: LedgerData):
    """Run automated verification and record the result."""
    v_result = VerificationResult(result)
    # Run the engine
    from verification.engine import verify as run_verify
    report = run_verify(tx_id, ledger)
    # Record outcome
    tx = record_verification_result(tx_id, v_result)
    return {
        "transaction": tx.to_dict(),
        "verification": report.to_dict(),
    }


@router.post("/transactions/{tx_id}/settle")
async def api_settle(tx_id: str):
    tx = _settle_tx(tx_id)
    return {"transaction": tx.to_dict(), "status": "settled"}


@router.post("/transactions/{tx_id}/dispute")
async def api_dispute(tx_id: str):
    tx = _dispute_tx(tx_id)
    return {"transaction": tx.to_dict(), "status": "disputed"}


@router.post("/transactions/{tx_id}/cancel")
async def api_cancel(tx_id: str):
    tx = _cancel_tx(tx_id)
    return {"transaction": tx.to_dict(), "status": "cancelled"}


# ── Bookkeepers ────────────────────────────────────────────────────────────────

_bookkeepers: dict[str, Bookkeeper] = {}
_owners: dict[str, BusinessOwner] = {}


@router.post("/bookkeepers")
async def api_create_bookkeeper(
    name: str,
    email: str,
    tier: str = "starter",
    bio: str = "",
):
    bk = Bookkeeper(name=name, email=email, tier=BookkeeperTier(tier), bio=bio)
    _bookkeepers[bk.bookkeeper_id] = bk
    return {"bookkeeper": bk.to_dict(), "status": "created"}


@router.get("/bookkeepers")
async def api_list_bookkeepers():
    return {"bookkeepers": [b.to_dict() for b in _bookkeepers.values()]}


@router.get("/bookkeepers/{bk_id}")
async def api_get_bookkeeper(bk_id: str):
    bk = _bookkeepers.get(bk_id)
    if not bk:
        raise HTTPException(status_code=404, detail="Bookkeeper not found")
    return {"bookkeeper": bk.to_dict()}


# ── Business Owners ────────────────────────────────────────────────────────────

@router.post("/owners")
async def api_create_owner(
    name: str,
    email: str,
    business_name: str,
):
    owner = BusinessOwner(name=name, email=email, business_name=business_name)
    _owners[owner.owner_id] = owner
    return {"owner": owner.to_dict(), "status": "created"}


@router.get("/owners")
async def api_list_owners():
    return {"owners": [o.to_dict() for o in _owners.values()]}


@router.get("/owners/{owner_id}")
async def api_get_owner(owner_id: str):
    owner = _owners.get(owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    return {"owner": owner.to_dict()}


# ── Verification API ───────────────────────────────────────────────────────────

@router.post("/verify/submit")
async def api_verify(tx_id: str, ledger: LedgerData):
    """Submit ledger data for automated verification."""
    report = verify(tx_id, ledger)
    return {"verification": report.to_dict()}