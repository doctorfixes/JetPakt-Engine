"""Marketplace data models — Post → Bid → Escrow → Execute → Verify → Settle."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


# ── Enums ──────────────────────────────────────────────────────────────────────

class TransactionStatus(str, Enum):
    """Lifecycle of a marketplace transaction."""
    POSTED = "posted"          # Owner submitted the close
    BIDDING = "bidding"        # Bookkeepers reviewing & competing
    BIDDING_CLOSED = "bidding_closed"  # Bookkeeper selected, moving to escrow
    IN_ESCROW = "in_escrow"    # Payment held via Stripe
    EXECUTING = "executing"    # Bookkeeper is reconciling accounts
    VERIFYING = "verifying"    # Automated verification running
    VERIFIED = "verified"      # Accounts reconciled, ready to settle
    SETTLED = "settled"        # Payment released, scores updated
    DISPUTED = "disputed"      # Verification failed, escalation
    CANCELLED = "cancelled"    # Owner or bookkeeper cancelled before escrow release


class BidStatus(str, Enum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class VerificationResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"


class BookkeeperTier(str, Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    SENIOR = "senior"


# ── Business objects ──────────────────────────────────────────────────────────

class Post:
    """A business owner's month-end close submission."""

    def __init__(
        self,
        *,
        post_id: str | None = None,
        owner_id: str,
        business_name: str,
        period_end: str,          # ISO date string e.g. "2026-05-31"
        deadline: str,            # ISO date string
        budget_cents: int,        # Max budget in cents
        description: str,         # Scope description
        chart_of_accounts: str | None = None,  # File ref or URL
        bank_statements: list[str] | None = None,  # File refs or URLs
        status: TransactionStatus = TransactionStatus.POSTED,
        created_at: str | None = None,
        updated_at: str | None = None,
    ):
        self.post_id = post_id or f"post_{uuid.uuid4().hex[:12]}"
        self.owner_id = owner_id
        self.business_name = business_name
        self.period_end = period_end
        self.deadline = deadline
        self.budget_cents = budget_cents
        self.description = description
        self.chart_of_accounts = chart_of_accounts
        self.bank_statements = bank_statements or []
        self.status = status
        now = datetime.now(timezone.utc).isoformat()
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "owner_id": self.owner_id,
            "business_name": self.business_name,
            "period_end": self.period_end,
            "deadline": self.deadline,
            "budget_cents": self.budget_cents,
            "budget_dollars": f"${self.budget_cents / 100:.2f}",
            "description": self.description,
            "chart_of_accounts": self.chart_of_accounts,
            "bank_statements": self.bank_statements,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Post:
        return cls(**data)


class Bid:
    """A bookkeeper's bid on a post."""

    def __init__(
        self,
        *,
        bid_id: str | None = None,
        post_id: str,
        bookkeeper_id: str,
        price_cents: int,
        turnaround_days: int,
        cover_note: str = "",
        status: BidStatus = BidStatus.ACTIVE,
        created_at: str | None = None,
    ):
        self.bid_id = bid_id or f"bid_{uuid.uuid4().hex[:12]}"
        self.post_id = post_id
        self.bookkeeper_id = bookkeeper_id
        self.price_cents = price_cents
        self.turnaround_days = turnaround_days
        self.cover_note = cover_note
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def __lt__(self, other: "Bid") -> bool:
        """Sort by price ascending."""
        return self.price_cents < other.price_cents

    def to_dict(self) -> dict:
        return {
            "bid_id": self.bid_id,
            "post_id": self.post_id,
            "bookkeeper_id": self.bookkeeper_id,
            "price_cents": self.price_cents,
            "price_dollars": f"${self.price_cents / 100:.2f}",
            "turnaround_days": self.turnaround_days,
            "cover_note": self.cover_note,
            "status": self.status.value,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Bid:
        return cls(**data)


class Transaction:
    """A complete marketplace transaction across its lifecycle."""

    def __init__(
        self,
        *,
        tx_id: str | None = None,
        post_id: str,
        bookkeeper_id: str,
        accepted_bid_id: str,
        price_cents: int,
        status: TransactionStatus = TransactionStatus.IN_ESCROW,
        stripe_payment_intent_id: str | None = None,
        stripe_transfer_id: str | None = None,
        verification_result: VerificationResult = VerificationResult.PENDING,
        verification_report: dict | None = None,
        escrow_released_at: str | None = None,
        settled_at: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ):
        self.tx_id = tx_id or f"tx_{uuid.uuid4().hex[:12]}"
        self.post_id = post_id
        self.bookkeeper_id = bookkeeper_id
        self.accepted_bid_id = accepted_bid_id
        self.price_cents = price_cents
        self.status = status
        self.stripe_payment_intent_id = stripe_payment_intent_id
        self.stripe_transfer_id = stripe_transfer_id
        self.verification_result = verification_result
        self.verification_report = verification_report or {}
        self.escrow_released_at = escrow_released_at
        self.settled_at = settled_at
        now = datetime.now(timezone.utc).isoformat()
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "post_id": self.post_id,
            "bookkeeper_id": self.bookkeeper_id,
            "accepted_bid_id": self.accepted_bid_id,
            "price_cents": self.price_cents,
            "price_dollars": f"${self.price_cents / 100:.2f}",
            "status": self.status.value,
            "stripe_payment_intent_id": self.stripe_payment_intent_id,
            "stripe_transfer_id": self.stripe_transfer_id,
            "verification_result": self.verification_result.value,
            "verification_report": self.verification_report,
            "escrow_released_at": self.escrow_released_at,
            "settled_at": self.settled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Transaction:
        return cls(**data)


class Bookkeeper:
    """A vetted bookkeeper on the platform."""

    def __init__(
        self,
        *,
        bookkeeper_id: str | None = None,
        name: str,
        email: str,
        tier: BookkeeperTier = BookkeeperTier.STARTER,
        completed_jobs: int = 0,
        accuracy_score: float = 1.0,  # 0.0–1.0, tracks verification pass rate
        avg_rating: float = 0.0,      # 0.0–5.0
        stripe_account_id: str | None = None,
        bio: str = "",
        verified: bool = False,
        created_at: str | None = None,
    ):
        self.bookkeeper_id = bookkeeper_id or f"bk_{uuid.uuid4().hex[:12]}"
        self.name = name
        self.email = email
        self.tier = tier
        self.completed_jobs = completed_jobs
        self.accuracy_score = accuracy_score
        self.avg_rating = avg_rating
        self.stripe_account_id = stripe_account_id
        self.bio = bio
        self.verified = verified
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "bookkeeper_id": self.bookkeeper_id,
            "name": self.name,
            "email": self.email,
            "tier": self.tier.value,
            "completed_jobs": self.completed_jobs,
            "accuracy_score": self.accuracy_score,
            "avg_rating": self.avg_rating,
            "stripe_account_id": self.stripe_account_id,
            "bio": self.bio,
            "verified": self.verified,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Bookkeeper:
        return cls(**data)


class BusinessOwner:
    """A small business owner on the platform."""

    def __init__(
        self,
        *,
        owner_id: str | None = None,
        name: str,
        email: str,
        business_name: str,
        stripe_customer_id: str | None = None,
        completed_posts: int = 0,
        created_at: str | None = None,
    ):
        self.owner_id = owner_id or f"own_{uuid.uuid4().hex[:12]}"
        self.name = name
        self.email = email
        self.business_name = business_name
        self.stripe_customer_id = stripe_customer_id
        self.completed_posts = completed_posts
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "owner_id": self.owner_id,
            "name": self.name,
            "email": self.email,
            "business_name": self.business_name,
            "stripe_customer_id": self.stripe_customer_id,
            "completed_posts": self.completed_posts,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BusinessOwner:
        return cls(**data)