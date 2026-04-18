# jetpakt-site — Marketing Landing

Static marketing site for JetPakt, LLC. Built with hand-written HTML + CSS; no build step.

## Stack
- **HTML** — `index.html`
- **CSS** — `styles.css` (hospitality UX palette: teal `#20808D`, cream `#F7F6F2`)
- **Fonts** — Instrument Serif (display), Inter (UI), DM Sans (numeric) — all loaded from Google Fonts CDN

## Local preview
```bash
cd jetpakt-site
python3 -m http.server 8000
# then open http://localhost:8000
```

## Deployment
This folder is published by Netlify. Build config is in `../netlify.toml`:
- **base dir:** `jetpakt-site`
- **publish dir:** `.` (same folder, no transform)
- **build command:** none

Pushing to `main` auto-deploys via the Netlify → GitHub integration (set up once in the Netlify Dashboard).

## Sections
1. Hero — headline + CTA
2. How it works — Scan → Pulse → Drafts-only
3. Pricing — 5 tiers ($49 Scan → $1,499 Concierge)
4. Guardrails — defamation-safe, legal-review flags, auditable
5. Contact — email, phone, web
