"""Verification engine — arithmetic checks on bookkeeping accuracy.

The moat: every check is a binary, deterministic arithmetic comparison.
Either debits equal credits or they do not. No subjective judgments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable


class CheckSeverity(str, Enum):
    ERROR = "error"    # Must pass for verification to succeed
    WARN = "warn"      # Flag for review, doesn't block settlement


class CheckResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"  # Insufficient data to check


@dataclass
class VerificationCheck:
    """A single arithmetic verification check."""
    name: str
    description: str
    severity: CheckSeverity
    result: CheckResult = CheckResult.PASS
    expected: str | None = None
    actual: str | None = None
    detail: str | None = None


@dataclass
class VerificationReport:
    """Complete verification result for a transaction."""
    tx_id: str
    checks: list[VerificationCheck] = field(default_factory=list)
    overall: CheckResult = CheckResult.PASS
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.SKIP)

    def add(self, check: VerificationCheck) -> None:
        self.checks.append(check)
        if check.result == CheckResult.FAIL and check.severity == CheckSeverity.ERROR:
            self.overall = CheckResult.FAIL

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "overall": self.overall.value,
            "verified_at": self.verified_at,
            "checks": [
                {
                    "name": c.name,
                    "description": c.description,
                    "severity": c.severity.value,
                    "result": c.result.value,
                    "expected": c.expected,
                    "actual": c.actual,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
        }


# ── Input data structures ─────────────────────────────────────────────────────

@dataclass
class JournalEntry:
    """A single journal entry (one side of an entry)."""
    account: str
    debit_cents: int
    credit_cents: int
    description: str = ""


@dataclass
class LedgerData:
    """Data needed to verify a period's close."""
    period_end: str
    previous_balance_cents: int  # Retained earnings from prior period
    journal_entries: list[JournalEntry]
    ending_balances: dict[str, int]  # account_name -> balance_cents
    net_income_cents: int = 0       # Net income for the period (revenues - expenses)
    bank_statement_balance_cents: int | None = None


# ── Check implementations ─────────────────────────────────────────────────────

CheckFunction = Callable[[LedgerData], VerificationCheck]


# 1. DEBITS = CREDITS
def check_debits_equal_credits(ledger: LedgerData) -> VerificationCheck:
    """Fundamental accounting identity: sum(debits) == sum(credits)."""
    total_debits = sum(e.debit_cents for e in ledger.journal_entries)
    total_credits = sum(e.credit_cents for e in ledger.journal_entries)
    expected = f"{total_debits:,}"
    actual = f"{total_credits:,}"
    passed = total_debits == total_credits
    return VerificationCheck(
        name="debits_equal_credits",
        description="Sum of all debits equals sum of all credits for the period",
        severity=CheckSeverity.ERROR,
        result=CheckResult.PASS if passed else CheckResult.FAIL,
        expected=expected,
        actual=actual,
        detail="Total debits and credits match" if passed
               else f"Debits (${total_debits/100:.2f}) != Credits (${total_credits/100:.2f})",
    )


# 2. BANK STATEMENT MATCH
def check_bank_balance(ledger: LedgerData) -> VerificationCheck:
    """Cash account balance matches bank statement."""
    if ledger.bank_statement_balance_cents is None:
        return VerificationCheck(
            name="bank_statement_match",
            description="Cash account balance matches bank statement ending balance",
            severity=CheckSeverity.WARN,
            result=CheckResult.SKIP,
            detail="No bank statement provided for comparison",
        )
    cash_balance = ledger.ending_balances.get("Cash", 0)
    passed = cash_balance == ledger.bank_statement_balance_cents
    return VerificationCheck(
        name="bank_statement_match",
        description="Cash account balance matches bank statement ending balance",
        severity=CheckSeverity.WARN,
        result=CheckResult.PASS if passed else CheckResult.FAIL,
        expected=f"${ledger.bank_statement_balance_cents/100:.2f}",
        actual=f"${cash_balance/100:.2f}",
        detail="Cash balance matches bank statement" if passed
               else f"Cash balance (${cash_balance/100:.2f}) != Bank statement (${ledger.bank_statement_balance_cents/100:.2f})",
    )


# 3. PERIOD BALANCE CHECK
def check_period_balance(ledger: LedgerData) -> VerificationCheck:
    """Ensure retained earnings change matches the declared net income."""
    expected_retained = ledger.previous_balance_cents + ledger.net_income_cents
    actual_retained = ledger.ending_balances.get("Retained Earnings", 0)

    tolerance = 100  # $1 rounding tolerance
    diff = abs(expected_retained - actual_retained)
    passed = diff <= tolerance

    detail_parts = []
    if passed:
        detail_parts.append(f"Retained earnings within tolerance ({diff}¢ off)")
    else:
        detail_parts.append(f"Expected ${expected_retained/100:.2f}, got ${actual_retained/100:.2f}")
    detail_parts.append(f"Net income: ${ledger.net_income_cents/100:.2f}")

    if diff > tolerance:
        detail_parts.append(f"Difference: ${diff/100:.2f}")

    return VerificationCheck(
        name="period_balance",
        description="Retained earnings carry-forward matches net income",
        severity=CheckSeverity.ERROR,
        result=CheckResult.PASS if passed else CheckResult.FAIL,
        expected=f"${expected_retained/100:.2f}",
        actual=f"${actual_retained/100:.2f}",
        detail=" — ".join(detail_parts),
    )


# 4. TEMPORARY ACCOUNTS CLOSED
def check_temporary_accounts_closed(ledger: LedgerData) -> VerificationCheck:
    """Revenue, expense, and income summary accounts should be closed at period end."""
    temporary_accounts = ["Revenue", "Expenses", "Cost of Goods Sold",
                          "Operating Expenses", "Other Income", "Other Expenses",
                          "Income Summary", "Dividends"]
    open_temps = [
        (acct, bal) for acct, bal in ledger.ending_balances.items()
        if acct in temporary_accounts and bal != 0
    ]
    passed = len(open_temps) == 0
    return VerificationCheck(
        name="temporary_accounts_closed",
        description="All temporary accounts (revenue, expenses, dividends) closed to retained earnings",
        severity=CheckSeverity.ERROR,
        result=CheckResult.PASS if passed else CheckResult.FAIL,
        detail="All temporary accounts closed" if passed
               else f"Open temporary accounts: {', '.join(a for a, _ in open_temps)}",
    )


# 5. NON-NEGATIVE ASSETS
def check_non_negative_assets(ledger: LedgerData) -> VerificationCheck:
    """Asset accounts cannot have negative balances."""
    negative_assets = [
        (acct, bal) for acct, bal in ledger.ending_balances.items()
        if acct in ("Cash", "Accounts Receivable", "Inventory", "Prepaid Expenses")
        and bal < 0
    ]
    passed = len(negative_assets) == 0
    return VerificationCheck(
        name="non_negative_assets",
        description="Asset accounts have non-negative balances",
        severity=CheckSeverity.ERROR,
        result=CheckResult.PASS if passed else CheckResult.FAIL,
        detail="All asset accounts non-negative" if passed
               else f"Negative balances in: {', '.join(a for a, _ in negative_assets)}",
    )


# ── Verifier ───────────────────────────────────────────────────────────────────

DEFAULT_CHECKS: list[CheckFunction] = [
    check_debits_equal_credits,
    check_bank_balance,
    check_period_balance,
    check_temporary_accounts_closed,
    check_non_negative_assets,
]


def verify(
    tx_id: str,
    ledger: LedgerData,
    checks: list[CheckFunction] | None = None,
) -> VerificationReport:
    """Run all verification checks against a ledger and return the report."""
    report = VerificationReport(tx_id=tx_id)
    for check_fn in (checks or DEFAULT_CHECKS):
        result = check_fn(ledger)
        report.add(result)
    return report