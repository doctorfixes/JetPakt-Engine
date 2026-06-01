"""Bid phase — bookkeepers review posts and compete on price/turnaround."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import Bid, BidStatus, TransactionStatus
from .post import get_post, update_post_status


_bids: dict[str, Bid] = {}


def place_bid(
    post_id: str,
    bookkeeper_id: str,
    price_cents: int,
    turnaround_days: int,
    cover_note: str = "",
) -> Bid:
    """Place a bid on an open post."""
    post = get_post(post_id)
    if not post:
        raise ValueError(f"Post not found: {post_id}")
    if post.status not in (TransactionStatus.POSTED, TransactionStatus.BIDDING):
        raise ValueError(f"Post is not accepting bids (status: {post.status.value})")

    # Auto-advance post to BIDDING on first bid
    if post.status == TransactionStatus.POSTED:
        update_post_status(post_id, TransactionStatus.BIDDING)

    bid = Bid(
        post_id=post_id,
        bookkeeper_id=bookkeeper_id,
        price_cents=price_cents,
        turnaround_days=turnaround_days,
        cover_note=cover_note,
        status=BidStatus.ACTIVE,
    )
    _bids[bid.bid_id] = bid
    return bid


def get_bid(bid_id: str) -> Bid | None:
    return _bids.get(bid_id)


def list_bids(post_id: str, status: BidStatus | None = None) -> list[Bid]:
    bids = [b for b in _bids.values() if b.post_id == post_id]
    if status:
        bids = [b for b in bids if b.status == status]
    return sorted(bids, key=lambda b: b.price_cents)


def accept_bid(bid_id: str) -> Bid:
    """Owner accepts a bid. Closes bidding and transitions to escrow-ready."""
    bid = get_bid(bid_id)
    if not bid:
        raise ValueError(f"Bid not found: {bid_id}")

    bid.status = BidStatus.ACCEPTED
    _bids[bid_id] = bid

    # Reject all other active bids on this post
    for other in list_bids(bid.post_id, BidStatus.ACTIVE):
        if other.bid_id != bid_id:
            other.status = BidStatus.REJECTED
            _bids[other.bid_id] = other

    # Advance post
    update_post_status(bid.post_id, TransactionStatus.BIDDING_CLOSED)

    return bid


def withdraw_bid(bid_id: str) -> Bid:
    bid = get_bid(bid_id)
    if not bid:
        raise ValueError(f"Bid not found: {bid_id}")
    if bid.status != BidStatus.ACTIVE:
        raise ValueError(f"Cannot withdraw bid with status: {bid.status.value}")
    bid.status = BidStatus.WITHDRAWN
    _bids[bid_id] = bid
    return bid