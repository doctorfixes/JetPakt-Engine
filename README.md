# JetPakt — Arithmetic-Verified Bookkeeping Marketplace

Post → Bid → Escrow → Execute → Verify → Settle

**JetPakt is the first marketplace where bookkeeping accuracy is guaranteed by automated arithmetic checks.** Business owners post their month-end closes, vetted bookkeepers compete on price and turnaround, and no payment is released until our verification engine confirms every number balances.

[gojetpakt.com](https://gojetpakt.com) — built by [doctorfixes](https://github.com/doctorfixes)

---

## The Lifecycle

| Phase | What Happens |
|-------|--------------|
| **Post** | Owner submits the month-end close: period, deadline, budget, chart of accounts, bank statements |
| **Bid** | Bookkeepers review and compete on price + turnaround |
| **Escrow** | Payment held via Stripe. Bookkeeper starts work. |
| **Execute** | Bookkeeper reconciles accounts |
| **Verify** | Automated checks: debits = credits, bank matches, periods balance, assets non-negative |
| **Settle** | If all checks pass → payment released, scores updated. If any fail → dispute. |

## The Moat: Arithmetic Verification

Every check is binary. No subjective judgments. No star ratings needed.

- **Debits = Credits** — The fundamental accounting identity. Hard constraint.
- **Bank Statement Match** — Cash balance must match the bank's statement.
- **Period Balance** — Retained earnings correctly carry forward.
- **Zero Net Balance** — All accounts net to zero in double-entry.
- **Non-Negative Assets** — Asset accounts cannot go negative.

If any ERROR-level check fails, the transaction enters dispute. Payment stays in escrow.

## Quick Start

```bash
# Clone
git clone https://github.com/doctorfixes/JetPakt-Engine.git
cd JetPakt-Engine

# Install
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
uvicorn main:app --reload

# Visit
#   API:     http://localhost:8000/api/health
#   Docs:    http://localhost:8000/docs
#   Site:    http://localhost:8000/
```

## Project Structure

```
marketplace/         # Core marketplace logic
├── __init__.py
├── models.py        # Data models (Post, Bid, Transaction, etc.)
├── state_machine.py # Lifecycle state machine (enforces valid transitions)
├── post.py          # Post phase
├── bid.py           # Bid phase
└── escrow.py        # Escrow → Execute → Verify → Settle orchestration

verification/        # Arithmetic verification engine (the moat)
├── __init__.py
└── engine.py        # Checks, report generation, ledger validation

api/                 # FastAPI routes
├── __init__.py
└── routes/
    ├── __init__.py
    └── marketplace.py

stripe/              # Stripe escrow integration
├── __init__.py
└── escrow.py        # hold_payment, release_payment, etc.

site/                # Marketing site (GoJetPakt)
└── index.html

main.py              # FastAPI entrypoint
netlify.toml         # Netlify deploy config
```

## API Endpoints

### Posts
- `POST /api/posts` — Create a month-end close post
- `GET /api/posts` — List posts (optional `?status=`)
- `GET /api/posts/{id}` — Get post details
- `DELETE /api/posts/{id}` — Delete a post

### Bids
- `POST /api/posts/{id}/bids` — Place a bid
- `GET /api/posts/{id}/bids` — List bids on a post
- `POST /api/bids/{id}/accept` — Accept a bid (owner)
- `POST /api/bids/{id}/withdraw` — Withdraw a bid (bookkeeper)

### Transactions (Escrow → Execute → Verify → Settle)
- `POST /api/transactions` — Create transaction (move to escrow)
- `GET /api/transactions` — List transactions
- `GET /api/transactions/{id}` — Get transaction details
- `POST /api/transactions/{id}/execute` — Start execution
- `POST /api/transactions/{id}/verify-submit` — Submit for verification
- `POST /api/transactions/{id}/verify-result` — Record verification result
- `POST /api/transactions/{id}/settle` — Release payment
- `POST /api/transactions/{id}/dispute` — Flag dispute
- `POST /api/transactions/{id}/cancel` — Cancel transaction

### Accounts
- `POST /api/bookkeepers` — Register a bookkeeper
- `GET /api/bookkeepers` — List bookkeepers
- `POST /api/owners` — Register a business owner
- `GET /api/owners` — List owners

### Verification
- `POST /api/verify/submit` — Submit ledger for automated verification

## Development

```bash
# Install deps
pip install fastapi uvicorn stripe

# Run with hot-reload
uvicorn main:app --reload

# View API docs at http://localhost:8000/docs
```

## Deployment

- **Marketing site**: Deploys to Netlify from `site/` → gojetpakt.com
- **API backend**: FastAPI app, deployable as Netlify Functions or standalone service
- **Stripe**: Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` env vars for production

## License

MIT
