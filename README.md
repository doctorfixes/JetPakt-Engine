# JetPakt

Real-time restaurant operations alert engine.

## What it does

JetPakt detects operational issues during live shifts and alerts operators
before they impact revenue.

## Example

Lunch shift:

* Sales: +22% vs forecast
* Labor: below target
* Ticket times rising

→ JetPakt alert: "Call in staff immediately"

## How it works

**Inputs:**

* POS (sales)
* Labor (staffing)
* Reviews (complaints)
* Delivery demand

**Engine:**

* Simple rule-based alerts

**Output:**

* Slack alerts
* Email summaries

## Run locally

```bash
uvicorn main:app --reload
```

## Vision

JetPakt replaces reactive management with real-time operational decisions.
