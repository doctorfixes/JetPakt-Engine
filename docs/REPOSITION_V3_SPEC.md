# JetPakt Reposition v3 — Drift Diagnosis, Five Pillars

**Date:** 2026-04-18
**Status:** Spec, pre-apply. Redline this, then propagate.
**Source of truth:** `docs/ROS_FRAMEWORK.md` (five pillars, 24 cases), `scan_engine.py` (10 signals, severity, peer benchmark, pillar rollup), `roi_engine.py` (Luca elasticity + peak-hour uplift + local check averages).

---

## 1. Positioning thesis

JetPakt is not a review-management product. It is a **drift-diagnosis system for independent restaurants**. Reviews are the cheapest public signal a business leaks, so they are the acquisition wedge, but they are one input among several into a five-pillar operating-system diagnosis (Production, Service, Sales, Operations, Management). The deliverable is an operator memo with a dominant-pillar rollup, a mapped ROS case, a 30/60/90 day plan, and a monthly revenue-recovery range.

One-line test: if a reader comes away thinking the product is a review scanner, the copy has failed.

---

## 2. Site — canonical copy blocks

### 2.1 Hero

**Eyebrow:** Drift diagnosis for independent restaurants

**Headline:** Most restaurants fail from quiet drift, not one big mistake.

**Subhead:** JetPakt reads the signals your restaurant leaks in public — reviews, pacing patterns, peer benchmarks, fee language, rating velocity — and returns a one-page operator memo. Which of the five pillars is drifting. What it is costing per month. What you move in the next ninety days. Reviews are the front door. Operations are the work.

**Primary CTA:** Request a free one-page preview
**Secondary CTA:** See the method

**Hero proofs (3):**
- Diagnosis across five operating pillars: Production, Service, Sales, Operations, Management
- Monthly revenue-recovery range anchored in Luca elasticity and local check averages
- Legal-review flags on wage, fee, and disclosure language — routed to your attorney, never posted

### 2.2 Positioning / Who this is for

**Section header:** For operators who read their own reviews and sign their own checks.

**Lede:** JetPakt is built for the independent or small-group operator with fewer than five locations, hospitality-adjacent, owner-operated. The work is advisory — you receive a short memo, you keep every approval gate. We are not a dashboard, not an auto-responder, not a marketing agency.

**For you if:**
- You run one to four restaurants, cafes, bars, or hospitality rooms
- You have watched your rating slide and cannot point to a single cause
- You already know the problem is operational — pacing, consistency, staffing, pricing — and you want it named, quantified, and sequenced
- You want a diagnosis with a number attached to it, not another login

**Not for you if:**
- You want bulk review generation, auto-replies, or AI ghost-written responses
- You are an enterprise group wanting a dashboard for a district manager
- You want a marketing retainer, social posts, or paid-media management

### 2.3 Method — the five pillars

**Section header:** A restaurant is five systems. Drift shows up in one, then spreads.

**Lede:** The Restaurant Operating System framework treats operating a restaurant as an engineering problem with a human core. Every JetPakt diagnosis maps evidence to one of the five pillars, to a specific drift case, and to the operating principles that resolve it.

**Five pillar cards (keep short):**

- **Production — Kitchen.** Every plate built to spec, every shift. Drift shows up as food-quality variance, expo bottlenecks, safety-log skips. Mapped principles: Six Sigma, Theory of Constraints, Reliability Engineering.
- **Service — Front of house.** Hospitality engineered as a system. Drift shows up as pacing complaints, inconsistent steps of service, room ambience. Mapped principles: Drucker, Situational Leadership, Broken Windows.
- **Sales — Menu and demand.** The menu as an engine, not a list. Drift shows up as pricing-value complaints, check-size compression, fee-transparency issues. Mapped principles: Menu Engineering, Kahneman, Game Theory.
- **Operations — Infrastructure.** The restaurant as a reliable machine. Drift shows up as staffing fragility, peak-hour collapse, turnover-driven understaffing. Mapped principles: Herzberg, Systems Thinking.
- **Management — Leadership rhythm.** The weekly cadence that compounds excellence. Drift shows up as billing-control issues, P&L blind spots, cash-handling exceptions. Mapped principles: Principal-Agent, Verification, Weekly Review Cadence.

### 2.4 Deliverables

**Section header:** One memo. Three headline outputs. Everything anchored to a public source.

**Primary deliverable — the Operator Memo (what used to be "the Scan"):**

- **Dominant-pillar rollup.** Which of the five pillars carries the most severity-weighted evidence right now, with the second and third pillars ranked underneath.
- **ROS case match.** The 24-case library (I01 through I24) supplies the symptom cluster, the root-cause hypothesis, and the operating principles that resolve it. Every memo names at least one case.
- **Monthly revenue-recovery range.** Low, mid, and high monthly recovery, computed from Luca rating elasticity, peak-hour uplift per half-star, and a local check-average lookup. Cited, not asserted.
- **30 / 60 / 90 day owner plan.** Concrete moves, owner-side, indexed to the pillar and case. These read like line items on a managers' meeting agenda, not marketing platitudes.
- **Legal-review flag list.** Wage, fee, disclosure, and food-safety language — excerpted verbatim, tagged for your attorney, never responded to automatically.
- **Response-draft pack.** Defamation-safe drafts for the most recent and most severe reviews. Drafts only. You publish.

**Secondary deliverable — the Drift Monitor (what used to be "the Pulse"):**

- Weekly or monthly diff on rating, volume, signal mix, peer gap, pillar rollup, and legal surface
- Dominant-pillar-change alerts (e.g. "Service pillar overtook Production this week")
- Same-day escalation on HIGH-severity events with an owner-only routing gate

### 2.5 Methodology — what the engine actually does

**Section header:** The method is boring. The output is not.

- **10 hospitality-specific signals.** Food quality, food safety, service pacing, service fee transparency, cleanliness, staffing, billing disputes, noise ambience, server attitude, pricing value. Generic sentiment treats a billing-disputes 1-star the same as a noise-ambience 1-star. We don't.
- **Severity with recency half-life.** Review signals decay (540-day half-life, 0.55 floor). Operational signals like pacing and billing persist because the underlying condition usually does. An old unaddressed problem still counts.
- **Peer benchmarking with Bayesian shrinkage.** A tiny-count outlier does not dominate a peer average. Your peer delta is honest.
- **Pillar rollup.** Every signal carries a pillar tag and case references. The memo's headline is which pillar owns the drift, not which review stung the most.
- **Revenue model.** Luca (HBS) elasticity + Anderson-Magruder peak uplift + One-Haus local check averages + Denver CVB labor load. Range, not point estimate. Every input cited on the page.

### 2.6 Pricing — re-anchored

**Section header:** Diagnose first. Monitor only if the diagnosis earns it.

**Primary tier — Drift Diagnosis (Operator Memo).** Keep $49 one-time for this pass. Describe it as: "A complete five-pillar drift diagnosis of your business, delivered as a short owner memo with a dominant-pillar rollup, a mapped ROS case, a monthly revenue-recovery range, a 30/60/90 plan, and a response-draft pack. Public sources only. Drafts-only delivery."

Scan features list becomes:
- Five-pillar drift diagnosis with case-ID match
- Monthly revenue-recovery range (low/mid/high, source-cited)
- 30/60/90 day owner plan, indexed to pillar and case
- Top-severity verbatim evidence with public source URLs
- Legal-review flag list with statute references
- Response-draft pack, drafts-only

**Subscription tiers — Drift Monitor.**

- **Essentials — $149/mo.** Monthly Drift Monitor. Rating, review-count, pillar-rollup diff. New legal-flag alerts.
- **Pro — $399/mo.** Weekly Drift Monitor. Peer-gap tracking. Pillar-mix diff with rank changes. Same-day alerts on HIGH events.
- **Alert — $899/mo.** Everything in Pro. Crisis-alert pathway. Response war-room drafts. Attorney-routing gate.
- **Concierge — $1,499/mo.** Everything in Alert. SMS to the owner on HIGH events. Monthly strategy review on the pillar roadmap.

### 2.7 FAQ — delta vs current

Add / replace these three answers (rest can stand for now):

**Q: Is this review-response software?**
A: No. Review response is one output of one layer of the product. The core product is a drift diagnosis across five operating pillars — Production, Service, Sales, Operations, Management — with a revenue-recovery range and a 30/60/90 owner plan. Reviews are the cheapest public signal, so they are the front door, but they are not the product.

**Q: What does a memo actually look like?**
A: One page, operator-legible. Top block: dominant-pillar rollup, ROS case match, monthly revenue-recovery range. Middle block: evidence, verbatim, source URLs. Bottom block: 30/60/90 plan and legal-flag list. Request a free preview and we'll send a one-page sample drawn entirely from your public record within two business days.

**Q: How is the revenue-recovery number calculated?**
A: Luca (HBS 12-016) rating elasticity, Anderson-Magruder peak-hour uplift, One-Haus local check averages, Denver CVB labor-load figures. Range not point estimate. Every input and URL is printed in the memo footnote. No dashboards, no black box.

---

## 3. Scan PDF (Operator Memo) — cover + intro rewrite

**Cover title:** Operator Memo
**Cover subtitle:** Five-pillar drift diagnosis · {business_name}
**Cover date line:** {month} {year} · prepared for {owner_name or "the owner"}

**Intro paragraph (above-the-fold, page 1):**

> This memo reads {business_name}'s public record as operating signals across five pillars: Production, Service, Sales, Operations, and Management. The dominant pillar this period is {dominant_pillar}, driven primarily by {top_signal_label} and matched to ROS case {top_case_id}. The recovery math on the next page estimates what pulling this drift back is worth per month. The plan underneath is what the owner moves in the next 90 days.

**Three-up block at top of memo (new — replaces the current severity grid as the headline):**

| Dominant pillar | ROS case | Monthly recovery (mid) |
|---|---|---|
| {pillar_name} | {case_id} — {case_oneliner} | ${recovery_mid}/mo (range ${recovery_low}–${recovery_high}) |

Current severity grid stays, but moves below the three-up block.

## 4. Pulse PDF (Drift Monitor) — lead-section rewrite

**Page-1 header:** Drift Monitor — {period_label}
**Lead sentence:** Dominant pillar this period is **{dominant_pillar}** ({rank_change}). Rating moved **{rating_delta}** against a peer gap of **{peer_gap}**. {legal_flag_line}.

Rating delta is no longer the headline — pillar change is.

## 5. Outreach template v3 — drift-first

### 5.1 Auto-built per-prospect drafts

**Subject format:** "A drift pattern in {short_name} reviews" (≤45 chars as before)

**Body skeleton (replaces current template):**

> Hi,
>
> Reading the last ninety reviews of {short_name}, the same operating signal is repeating: {top_signal_plain_english}. In the Restaurant Operating System frame this is a **{pillar_name}-pillar drift**, specifically case {case_id} ({case_oneliner}). It is the kind of pattern that shows up in reviews after it has already been costing covers for a quarter or two.
>
> I built JetPakt to read that pattern for independent owner-operators and return a one-page memo: which pillar is drifting, what it is costing per month, and what the owner moves in the next ninety days. Reviews are the front door. The five pillars are the product.
>
> Two quotes from your own public record, verbatim:
>
>     "{verbatim_quote_1}"
>     — {source_1}
>
>     "{verbatim_quote_2}"
>     — {source_2}
>
> {legal_flag_paragraph_if_HIGH}
>
> If a one-page preview would be useful, the inquiry form at gojetpakt.com comes straight to me. No sales call, no commitment.
>
> Ryan B., JetPakt Solutions
> gojetpakt.us@outlook.com  ·  gojetpakt.com

### 5.2 Generic warmup — drift-first version

**Subject:** A drift pattern I keep seeing in reviews (41 chars)

**Body:**

> Hi,
>
> When an independent restaurant loses a quarter-star over a quarter, the explanation is almost always operational drift showing up in reviews late. Two signals repeat, usually on specific shifts or specific days, and the owner is the last person with the time to read end-to-end.
>
> I built JetPakt for that problem. It reads the public record for independent owner-operators and returns a one-page operator memo: which of the five operating pillars is drifting (Production, Service, Sales, Operations, or Management), what it is costing per month in recoverable revenue, and what the owner moves in the next 30, 60, and 90 days. Reviews are the front door. The five pillars are the product.
>
> The method in one breath:
>
> - Every finding anchored to a verbatim public review or public record.
> - Severity with recency half-life; operational drift signals persist, review signals decay.
> - Peer benchmark with Bayesian shrinkage so a tiny-count outlier does not skew the delta.
> - Luca rating elasticity and local check averages to compute a monthly recovery range.
> - Legal-flag items routed to the owner's attorney. No auto-posts. No staff names. Drafts only.
>
> No ask in this note. If it is ever useful, the method and a sample lives at gojetpakt.com.
>
> Ryan B., JetPakt Solutions
> gojetpakt.us@outlook.com  ·  gojetpakt.com

---

## 6. Taxonomy changes — one-page find-and-replace

| Old (user-facing) | New (user-facing) |
|---|---|
| Reputation intelligence | Drift diagnosis |
| JetPakt Scan | Drift Diagnosis (Operator Memo) |
| JetPakt Pulse | Drift Monitor |
| 8-pillar severity matrix | Five-pillar drift diagnosis |
| Complaint severity | Signal severity |
| Owner PDF | Operator memo |
| Response-template pack | Response-draft pack |
| "Watch your rating" | "Monitor drift across the five pillars" |
| "Reputation, legal exposure, and operational risk" | "Operational drift, legal exposure, and revenue recovery" |

Terms to keep unchanged: Legal-review flag, HB25 1090, verbatim, drafts-only, peer gap, 30/60/90 plan.

---

## 7. What does NOT change in this pass

- Existing pricing dollar amounts ($49, $149, $399, $899, $1,499)
- Signature: "Ryan B., JetPakt Solutions / gojetpakt.us@outlook.com · gojetpakt.com"
- All guardrails: drafts-only, no staff names, verbatim anchoring, legal-flag routing to attorney, no auto-posting, no auto-solicitation
- Template rules: no em-dashes in author body, two-line signature, subject ≤45 chars, HB25 1090 with space
- Pulse cadence thresholds and same-day-alert gates
- Payment, Stripe, and billing integration
- Wordmark watermark footer on PDFs

---

## 8. Rollout sequence (once this spec is approved)

1. Site: `index.html` (hero → pricing → FAQ), `inquiry.html` (sync nav/headline if needed), `styles.css` (only if new components needed — unlikely)
2. PDFs: `scan_pdf.py` (cover + intro + three-up header block), `pulse_report.py` (lead section)
3. Engine: `outreach_builder.py` (template v3 with drift hook + pillar naming), `tests/test_outreach_builder.py` (assertion updates)
4. Regenerate: 5 lowprofile drafts + generic warmup against new copy
5. Test: `pytest` full suite, render test scan + pulse PDFs, Playwright visual QA of site
6. Ship: commit + push + verify gojetpakt.com deploys clean

---

*End of spec.*
