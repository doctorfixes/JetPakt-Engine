"""Stripe escrow integration — hold and release payments.

In production this handles actual Stripe API calls. For now it provides
the interface that marketplace/escrow.py depends on, with a mock mode
for local development."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional

import stripe

# ── Configuration ─────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PLATFORM_FEE_PERCENT = Decimal("0.10")  # 10% platform fee
DEV_MODE = not bool(STRIPE_SECRET_KEY)

if not DEV_MODE:
    stripe.api_key = STRIPE_SECRET_KEY


# ── Mock state for dev ─────────────────────────────────────────────────────────

_mock_payment_intents: dict[str, dict] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def hold_payment(
    amount_cents: int,
    customer_id: str,
    destination_account_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Hold a payment in escrow. Returns payment intent details.

    In dev mode (no STRIPE_SECRET_KEY), returns a mock payment intent.
    """
    if DEV_MODE:
        intent_id = f"pi_mock_{len(_mock_payment_intents) + 1:06d}"
        intent = {
            "id": intent_id,
            "amount": amount_cents,
            "currency": "usd",
            "status": "requires_capture",
            "customer": customer_id,
            "metadata": metadata or {},
            "destination": destination_account_id,
            "platform_fee_cents": int(amount_cents * PLATFORM_FEE_PERCENT),
        }
        _mock_payment_intents[intent_id] = intent
        return intent

    # Real Stripe call — requires payment_method from checkout
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        customer=customer_id,
        capture_method="manual",  # Hold, don't capture yet
        metadata=metadata or {},
        application_fee_amount=int(amount_cents * PLATFORM_FEE_PERCENT),
    )
    return {"id": intent.id, "amount": intent.amount, "status": intent.status, "client_secret": intent.client_secret}


def release_payment(payment_intent_id: str) -> dict:
    """Release escrow — capture the held payment.

    In dev mode, marks the mock intent as captured.
    """
    if DEV_MODE:
        intent = _mock_payment_intents.get(payment_intent_id)
        if not intent:
            raise ValueError(f"Mock payment intent not found: {payment_intent_id}")
        intent["status"] = "succeeded"
        return intent

    captured = stripe.PaymentIntent.capture(payment_intent_id)
    return {"id": captured.id, "status": captured.status, "amount": captured.amount}


def cancel_payment(payment_intent_id: str) -> dict:
    """Cancel/reverse an escrow payment.

    In dev mode, marks the mock intent as cancelled.
    """
    if DEV_MODE:
        intent = _mock_payment_intents.get(payment_intent_id)
        if not intent:
            raise ValueError(f"Mock payment intent not found: {payment_intent_id}")
        intent["status"] = "cancelled"
        return intent

    cancelled = stripe.PaymentIntent.cancel(payment_intent_id)
    return {"id": cancelled.id, "status": "cancelled"}


def create_account_link(account_id: str, refresh_url: str, return_url: str) -> str:
    """Create a Stripe account link for onboarding a bookkeeper."""
    if DEV_MODE:
        return f"{return_url}?mock_account_link=true&account_id={account_id}"
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


def get_balance(payment_intent_id: str) -> int:
    """Get remaining balance on a payment intent (in cents)."""
    if DEV_MODE:
        intent = _mock_payment_intents.get(payment_intent_id)
        if not intent or intent["status"] == "cancelled":
            return 0
        if intent["status"] == "succeeded":
            return 0
        return intent["amount"]
    intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    return intent.amount - (intent.amount_capturable or 0)