"""Tests for the JetPakt marketplace — full lifecycle coverage."""

from __future__ import annotations

import pytest

from marketplace.models import (
    Bid,
    BidStatus,
    Bookkeeper,
    BookkeeperTier,
    BusinessOwner,
    Post,
    Transaction,
    TransactionStatus,
    VerificationResult,
)
from marketplace.state_machine import (
    active_statuses,
    can_transition,
    terminal_statuses,
    transition,
    transition_on_verify,
)
from stripe.escrow import (
    _mock_payment_intents,
    cancel_payment,
    get_balance,
    hold_payment,
    release_payment,
)


# ── Models ─────────────────────────────────────────────────────────────────────

class TestModels:
    def test_post_generates_id_and_timestamps(self):
        p = Post(owner_id="o1", business_name="Biz", period_end="2026-05-31",
                 deadline="2026-06-07", budget_cents=100000, description="Test")
        assert p.post_id.startswith("post_")
        assert p.created_at is not None
        assert p.updated_at == p.created_at
        assert p.status == TransactionStatus.POSTED

    def test_post_to_dict_includes_all_fields(self):
        p = Post(owner_id="o1", business_name="Biz", period_end="2026-05-31",
                 deadline="2026-06-07", budget_cents=100000, description="Test",
                 chart_of_accounts="coa.csv", bank_statements=["stmt.pdf"])
        d = p.to_dict()
        assert d["owner_id"] == "o1"
        assert d["business_name"] == "Biz"
        assert d["budget_cents"] == 100000
        assert d["chart_of_accounts"] == "coa.csv"
        assert d["bank_statements"] == ["stmt.pdf"]
        assert d["post_id"].startswith("post_")

    def test_bid_sorts_by_price(self):
        b1 = Bid(post_id="p1", bookkeeper_id="bk1", price_cents=20000, turnaround_days=3)
        b2 = Bid(post_id="p1", bookkeeper_id="bk2", price_cents=15000, turnaround_days=5)
        assert b2 < b1  # lower price should sort first

    def test_bid_to_dict(self):
        b = Bid(post_id="p1", bookkeeper_id="bk1", price_cents=25000, turnaround_days=4, cover_note="I do good work")
        d = b.to_dict()
        assert d["bookkeeper_id"] == "bk1"
        assert d["cover_note"] == "I do good work"
        assert d["bid_id"].startswith("bid_")

    def test_transaction_default_status(self):
        t = Transaction(post_id="p1", bookkeeper_id="bk1", accepted_bid_id="b1", price_cents=50000)
        assert t.status == TransactionStatus.IN_ESCROW
        assert t.tx_id.startswith("tx_")

    def test_transaction_to_dict(self):
        t = Transaction(post_id="p1", bookkeeper_id="bk1", accepted_bid_id="b1",
                        price_cents=50000, stripe_payment_intent_id="pi_abc")
        d = t.to_dict()
        assert d["stripe_payment_intent_id"] == "pi_abc"
        assert d["price_cents"] == 50000

    def test_bookkeeper_default_tier(self):
        bk = Bookkeeper(name="Alice", email="alice@bk.com")
        assert bk.tier == BookkeeperTier.STARTER
        assert bk.bookkeeper_id.startswith("bk_")

    def test_bookkeeper_to_dict(self):
        bk = Bookkeeper(name="Alice", email="alice@bk.com", tier=BookkeeperTier.PROFESSIONAL, bio="CPA")
        d = bk.to_dict()
        assert d["tier"] == "professional"
        assert d["bio"] == "CPA"

    def test_business_owner_to_dict(self):
        o = BusinessOwner(name="Bob", email="bob@biz.com", business_name="Bob's Bakery")
        d = o.to_dict()
        assert d["business_name"] == "Bob's Bakery"
        assert d["owner_id"].startswith("own_")

    def test_verification_result_enum(self):
        assert VerificationResult.PASS.value == "pass"
        assert VerificationResult.FAIL.value == "fail"
        assert VerificationResult.PENDING.value == "pending"


# ── State Machine ──────────────────────────────────────────────────────────────

class TestStateMachine:
    def test_valid_transitions(self):
        assert can_transition(TransactionStatus.POSTED, TransactionStatus.BIDDING)
        assert can_transition(TransactionStatus.BIDDING, TransactionStatus.BIDDING_CLOSED)
        assert can_transition(TransactionStatus.BIDDING_CLOSED, TransactionStatus.IN_ESCROW)
        assert can_transition(TransactionStatus.IN_ESCROW, TransactionStatus.EXECUTING)
        assert can_transition(TransactionStatus.EXECUTING, TransactionStatus.VERIFYING)
        assert can_transition(TransactionStatus.VERIFYING, TransactionStatus.VERIFIED)
        assert can_transition(TransactionStatus.VERIFIED, TransactionStatus.SETTLED)

    def test_invalid_transitions(self):
        assert not can_transition(TransactionStatus.POSTED, TransactionStatus.EXECUTING)
        assert not can_transition(TransactionStatus.SETTLED, TransactionStatus.IN_ESCROW)
        assert not can_transition(TransactionStatus.CANCELLED, TransactionStatus.POSTED)
        assert not can_transition(TransactionStatus.DISPUTED, TransactionStatus.SETTLED)

    def test_any_to_disputed(self):
        """Dispute allowed from in-flight states: IN_ESCROW, EXECUTING, VERIFYING, VERIFIED."""
        for status in TransactionStatus:
            if status in (TransactionStatus.IN_ESCROW, TransactionStatus.EXECUTING,
                          TransactionStatus.VERIFYING, TransactionStatus.VERIFIED):
                assert can_transition(status, TransactionStatus.DISPUTED), \
                    f"Should allow dispute from {status}"

    def test_any_to_cancelled(self):
        """Cancel allowed from: POSTED, BIDDING, BIDDING_CLOSED, IN_ESCROW, DISPUTED."""
        for status in TransactionStatus:
            if status in (TransactionStatus.POSTED, TransactionStatus.BIDDING,
                          TransactionStatus.BIDDING_CLOSED, TransactionStatus.IN_ESCROW,
                          TransactionStatus.DISPUTED):
                assert can_transition(status, TransactionStatus.CANCELLED), \
                    f"Should allow cancel from {status}"

    def test_transition_func_valid(self):
        result = transition(TransactionStatus.POSTED, TransactionStatus.BIDDING)
        assert result == TransactionStatus.BIDDING

    def test_transition_func_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            transition(TransactionStatus.POSTED, TransactionStatus.EXECUTING)

    def test_transition_on_verify_pass(self):
        assert transition_on_verify(VerificationResult.PASS) == TransactionStatus.VERIFIED

    def test_transition_on_verify_fail(self):
        assert transition_on_verify(VerificationResult.FAIL) == TransactionStatus.DISPUTED

    def test_terminal_statuses(self):
        statuss = terminal_statuses()
        assert TransactionStatus.SETTLED.value in statuss
        assert TransactionStatus.CANCELLED.value in statuss

    def test_active_statuses(self):
        statuss = active_statuses()
        assert TransactionStatus.POSTED.value in statuss
        assert TransactionStatus.VERIFYING.value in statuss
        assert TransactionStatus.SETTLED.value not in statuss
        assert TransactionStatus.CANCELLED.value not in statuss

    def test_all_from_to_pairs(self):
        """Every valid transition through can_transition covers the expected paths."""
        assert can_transition(TransactionStatus.POSTED, TransactionStatus.BIDDING)
        assert can_transition(TransactionStatus.EXECUTING, TransactionStatus.VERIFYING)
        assert can_transition(TransactionStatus.VERIFYING, TransactionStatus.VERIFIED)
        assert can_transition(TransactionStatus.VERIFIED, TransactionStatus.SETTLED)
        assert not can_transition(TransactionStatus.POSTED, TransactionStatus.EXECUTING)
        assert not can_transition(TransactionStatus.SETTLED, TransactionStatus.IN_ESCROW)

    def test_transition_table_covers_all_statuses(self):
        """Verify can_transition can answer for every status."""
        for status in TransactionStatus:
            # Should not raise
            _ = can_transition(status, TransactionStatus.SETTLED)


# ── Post Layer ─────────────────────────────────────────────────────────────────

from marketplace.post import _posts as _post_store
from marketplace.post import create_post, delete_post, get_post, list_posts, update_post_status


class TestPostLayer:
    def setup_method(self):
        _post_store.clear()

    def test_create_and_retrieve(self):
        p = create_post("o1", "Biz", "2026-05-31", "2026-06-07", 100000, "Test")
        assert get_post(p.post_id) is p

    def test_list_all(self):
        create_post("o1", "A", "2026-05-01", "2026-06-01", 50000, "")
        create_post("o2", "B", "2026-05-01", "2026-06-01", 75000, "")
        assert len(list_posts()) == 2

    def test_list_by_status(self):
        create_post("o1", "A", "2026-05-01", "2026-06-01", 50000, "")
        posts = list_posts(TransactionStatus.POSTED)
        assert all(p.status == TransactionStatus.POSTED for p in posts)

    def test_update_status(self):
        p = create_post("o1", "Biz", "2026-05-31", "2026-06-07", 100000, "Test")
        updated = update_post_status(p.post_id, TransactionStatus.BIDDING)
        assert updated.status == TransactionStatus.BIDDING

    def test_delete(self):
        p = create_post("o1", "Biz", "2026-05-31", "2026-06-07", 100000, "Test")
        assert delete_post(p.post_id)
        assert get_post(p.post_id) is None

    def test_delete_missing(self):
        assert not delete_post("nonexistent")

    def test_get_missing(self):
        assert get_post("nonexistent") is None

    def test_update_missing_raises(self):
        with pytest.raises(ValueError, match="not found"):
            update_post_status("nonexistent", TransactionStatus.BIDDING)


# ── Bid Layer ──────────────────────────────────────────────────────────────────

from marketplace.bid import _bids as _bid_store
from marketplace.bid import place_bid, get_bid, list_bids, accept_bid, withdraw_bid


class TestBidLayer:
    def setup_method(self):
        _post_store.clear()
        _bid_store.clear()
        self.post = create_post("o1", "Biz", "2026-05-31", "2026-06-07", 100000, "Test")

    def test_place_bid(self):
        b = place_bid(self.post.post_id, "bk1", 50000, 3, "I can help")
        assert b.price_cents == 50000
        assert b.status == BidStatus.ACTIVE

    def test_place_bid_auto_advances_post(self):
        assert self.post.status == TransactionStatus.POSTED
        place_bid(self.post.post_id, "bk1", 50000, 3)
        assert self.post.status == TransactionStatus.BIDDING

    def test_place_bid_on_missing_post_raises(self):
        with pytest.raises(ValueError, match="not found"):
            place_bid("nonexistent", "bk1", 50000, 3)

    def test_list_bids_sorted_by_price(self):
        place_bid(self.post.post_id, "bk1", 80000, 5)
        place_bid(self.post.post_id, "bk2", 50000, 3)
        place_bid(self.post.post_id, "bk3", 60000, 4)
        bids = list_bids(self.post.post_id)
        prices = [b.price_cents for b in bids]
        assert prices == sorted(prices)

    def test_accept_bid(self):
        b1 = place_bid(self.post.post_id, "bk1", 80000, 5)
        b2 = place_bid(self.post.post_id, "bk2", 50000, 3)
        accepted = accept_bid(b2.bid_id)

        assert accepted.status == BidStatus.ACCEPTED
        # Other bids should be rejected
        assert get_bid(b1.bid_id).status == BidStatus.REJECTED

    def test_accept_bid_updates_post(self):
        b = place_bid(self.post.post_id, "bk1", 50000, 3)
        accept_bid(b.bid_id)
        from marketplace.post import get_post
        assert get_post(self.post.post_id).status == TransactionStatus.BIDDING_CLOSED

    def test_accept_missing_raises(self):
        with pytest.raises(ValueError, match="not found"):
            accept_bid("nonexistent")

    def test_withdraw_bid(self):
        b = place_bid(self.post.post_id, "bk1", 50000, 3)
        withdrawn = withdraw_bid(b.bid_id)
        assert withdrawn.status == BidStatus.WITHDRAWN

    def test_withdraw_non_active_raises(self):
        b = place_bid(self.post.post_id, "bk1", 50000, 3)
        withdraw_bid(b.bid_id)
        with pytest.raises(ValueError, match="Cannot withdraw"):
            withdraw_bid(b.bid_id)

    def test_list_bids_filtered_by_status(self):
        b = place_bid(self.post.post_id, "bk1", 50000, 3)
        active = list_bids(self.post.post_id, BidStatus.ACTIVE)
        assert len(active) == 1
        withdraw_bid(b.bid_id)
        active = list_bids(self.post.post_id, BidStatus.ACTIVE)
        assert len(active) == 0

    def test_bid_on_non_biddable_post_raises(self):
        """Bidding on a post that's already past bidding stage should fail."""
        b = place_bid(self.post.post_id, "bk1", 50000, 3)
        accept_bid(b.bid_id)
        with pytest.raises(ValueError, match="not accepting bids"):
            place_bid(self.post.post_id, "bk2", 40000, 2)


# ── Escrow/Transaction Layer ───────────────────────────────────────────────────

from marketplace.escrow import _transactions as _tx_store
from marketplace.escrow import (
    cancel,
    create_transaction,
    dispute,
    get_transaction,
    list_transactions,
    record_verification_result,
    settle,
    start_execution,
    submit_for_verification,
)


class TestEscrowLayer:
    def setup_method(self):
        _post_store.clear()
        _bid_store.clear()
        _tx_store.clear()
        self.post = create_post("o1", "Biz", "2026-05-31", "2026-06-07", 100000, "Test")
        self.bid = place_bid(self.post.post_id, "bk1", 50000, 3)
        self.accepted = accept_bid(self.bid.bid_id)

    def _tx(self):
        return create_transaction(self.post.post_id, "bk1", self.accepted.bid_id, 50000)

    def test_create_transaction(self):
        tx = self._tx()
        assert tx.status == TransactionStatus.IN_ESCROW
        assert tx.tx_id.startswith("tx_")

    def test_get_transaction(self):
        tx = self._tx()
        assert get_transaction(tx.tx_id) is tx

    def test_list_transactions(self):
        self._tx()
        assert len(list_transactions()) == 1
        assert len(list_transactions(TransactionStatus.IN_ESCROW)) == 1

    def test_get_missing_returns_none(self):
        assert get_transaction("nonexistent") is None

    def test_start_execution(self):
        tx = self._tx()
        tx = start_execution(tx.tx_id)
        assert tx.status == TransactionStatus.EXECUTING

    def test_submit_for_verification(self):
        tx = self._tx()
        tx = start_execution(tx.tx_id)
        tx = submit_for_verification(tx.tx_id, {"checks": 5})
        assert tx.status == TransactionStatus.VERIFYING
        assert tx.verification_report == {"checks": 5}

    def test_full_lifecycle(self):
        tx = self._tx()
        tx = start_execution(tx.tx_id)
        tx = submit_for_verification(tx.tx_id, {})
        tx = record_verification_result(tx.tx_id, VerificationResult.PASS)
        assert tx.status == TransactionStatus.VERIFIED
        assert tx.escrow_released_at is not None
        tx = settle(tx.tx_id)
        assert tx.status == TransactionStatus.SETTLED
        assert tx.settled_at is not None

    def test_verification_fail_goes_to_dispute(self):
        tx = self._tx()
        tx = start_execution(tx.tx_id)
        tx = submit_for_verification(tx.tx_id, {})
        tx = record_verification_result(tx.tx_id, VerificationResult.FAIL)
        assert tx.status == TransactionStatus.DISPUTED

    def test_dispute_from_any_state(self):
        tx = self._tx()
        tx = dispute(tx.tx_id)
        assert tx.status == TransactionStatus.DISPUTED

    def test_cancel_from_escrow(self):
        tx = self._tx()
        tx = cancel(tx.tx_id)
        assert tx.status == TransactionStatus.CANCELLED

    def test_nonexistent_operations_raise(self):
        with pytest.raises(ValueError, match="not found"):
            start_execution("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            settle("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            dispute("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            cancel("nonexistent")


# ── Verification Engine ────────────────────────────────────────────────────────

from verification.engine import (
    VerificationCheck,
    VerificationReport,
    CheckResult,
    CheckSeverity,
    JournalEntry,
    LedgerData,
    verify,
    check_debits_equal_credits,
    check_bank_balance,
    check_period_balance,
    check_temporary_accounts_closed,
    check_non_negative_assets,
)


class TestVerificationEngine:
    def _clean_ledger(self) -> LedgerData:
        """A ledger that should pass all checks."""
        return LedgerData(
            period_end="2026-05-31",
            previous_balance_cents=500000,
            net_income_cents=50000,
            journal_entries=[
                JournalEntry("Cash", 50000, 0, "Revenue collected"),
                JournalEntry("Revenue", 0, 50000, "Revenue recognized"),
                JournalEntry("Revenue", 50000, 0, "Close revenue"),
                JournalEntry("Retained Earnings", 0, 50000, "Close to retained"),
            ],
            ending_balances={"Cash": 50000, "Retained Earnings": 550000},
            bank_statement_balance_cents=50000,
        )

    def test_debits_equal_credits_passes(self):
        result = check_debits_equal_credits(self._clean_ledger())
        assert result.result == CheckResult.PASS

    def test_debits_equal_credits_fails(self):
        ledger = self._clean_ledger()
        ledger.journal_entries.append(JournalEntry("Cash", 100, 0, "Unbalanced"))
        result = check_debits_equal_credits(ledger)
        assert result.result == CheckResult.FAIL
        assert result.severity == CheckSeverity.ERROR

    def test_bank_balance_passes(self):
        result = check_bank_balance(self._clean_ledger())
        assert result.result == CheckResult.PASS

    def test_bank_balance_fails(self):
        ledger = self._clean_ledger()
        ledger.bank_statement_balance_cents = 40000
        result = check_bank_balance(ledger)
        assert result.result == CheckResult.FAIL
        assert result.severity == CheckSeverity.WARN

    def test_bank_balance_skips_when_no_statement(self):
        ledger = self._clean_ledger()
        ledger.bank_statement_balance_cents = None
        result = check_bank_balance(ledger)
        assert result.result == CheckResult.SKIP

    def test_period_balance_passes(self):
        result = check_period_balance(self._clean_ledger())
        assert result.result == CheckResult.PASS

    def test_period_balance_fails(self):
        ledger = self._clean_ledger()
        ledger.ending_balances["Retained Earnings"] = 600000  # Off by $100,000
        result = check_period_balance(ledger)
        assert result.result == CheckResult.FAIL

    def test_temporary_accounts_closed_passes(self):
        result = check_temporary_accounts_closed(self._clean_ledger())
        assert result.result == CheckResult.PASS

    def test_temporary_accounts_closed_fails(self):
        ledger = self._clean_ledger()
        ledger.ending_balances["Revenue"] = 50000
        result = check_temporary_accounts_closed(ledger)
        assert result.result == CheckResult.FAIL

    def test_non_negative_assets_passes(self):
        result = check_non_negative_assets(self._clean_ledger())
        assert result.result == CheckResult.PASS

    def test_non_negative_assets_fails(self):
        ledger = self._clean_ledger()
        ledger.ending_balances["Cash"] = -100
        result = check_non_negative_assets(ledger)
        assert result.result == CheckResult.FAIL

    def test_verify_returns_report(self):
        report = verify("tx_001", self._clean_ledger())
        assert report.tx_id == "tx_001"
        assert report.overall == CheckResult.PASS
        assert report.passed >= 4  # Most checks pass with clean data
        assert report.failed == 0

    def test_verify_with_explicit_checks(self):
        report = verify("tx_001", self._clean_ledger(), checks=[check_debits_equal_credits])
        assert len(report.checks) == 1

    def test_verify_fails_with_bad_data(self):
        ledger = self._clean_ledger()
        ledger.journal_entries = []
        ledger.ending_balances = {}
        report = verify("tx_bad", ledger)
        assert report.overall == CheckResult.FAIL

    def test_report_to_dict(self):
        report = verify("tx_001", self._clean_ledger())
        d = report.to_dict()
        assert d["tx_id"] == "tx_001"
        assert "checks" in d
        assert "overall" in d
        assert d["passed"] + d["failed"] + d["skipped"] == len(d["checks"])

    def test_check_dataclass(self):
        check = VerificationCheck(name="test", description="Test check",
                                  severity=CheckSeverity.WARN)
        assert check.result == CheckResult.PASS
        assert check.severity == CheckSeverity.WARN


# ── Stripe Dev Mode ────────────────────────────────────────────────────────────

class TestStripeDevMode:
    def setup_method(self):
        _mock_payment_intents.clear()

    def test_hold_payment_creates_mock_intent(self):
        pi = hold_payment(100000, "cus_001")
        assert pi["status"] == "requires_capture"
        assert pi["id"].startswith("pi_mock_")

    def test_hold_payment_calculates_fee(self):
        pi = hold_payment(100000, "cus_001")
        assert pi["platform_fee_cents"] == 10000  # 10% of 100000

    def test_release_payment(self):
        pi = hold_payment(50000, "cus_001")
        rel = release_payment(pi["id"])
        assert rel["status"] == "succeeded"

    def test_release_missing_raises(self):
        with pytest.raises(ValueError, match="not found"):
            release_payment("pi_mock_nonexistent")

    def test_cancel_payment(self):
        pi = hold_payment(50000, "cus_001")
        cancelled = cancel_payment(pi["id"])
        assert cancelled["status"] == "cancelled"

    def test_get_balance_after_release(self):
        pi = hold_payment(50000, "cus_001")
        release_payment(pi["id"])
        assert get_balance(pi["id"]) == 0

    def test_get_balance_after_cancel(self):
        pi = hold_payment(50000, "cus_001")
        cancel_payment(pi["id"])
        assert get_balance(pi["id"]) == 0

    def test_get_balance_before_action(self):
        pi = hold_payment(50000, "cus_001")
        assert get_balance(pi["id"]) == 50000

    def test_get_balance_missing_returns_zero(self):
        assert get_balance("pi_mock_nonexistent") == 0
