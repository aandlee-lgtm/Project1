# Sydney Flight Intelligence: product history, decisions and definitions

Running record of the owner's requests, the answers and decisions, and what shipped. Source for user
instructions, definitions and release notes. Open requests: [BACKLOG.md](BACKLOG.md).

---

## 1. History

### 2026-10-19 — Master build prompt; Phase 1 (provider feasibility)
**Asked for.** A production flight-intelligence service that finds genuinely bookable, well-priced
return fares from Sydney to Europe (priority 1, no transit through the Middle East or Turkey),
Japan (2) and China (3), 3–12 months ahead; explicit China Southern and Virgin Australia assessment
every cycle; verification before anything is recommended; history and scoring; a dashboard; a daily
email to two recipients. Start with Phase 1 and stop for approval on paid access and credentials.

**Found and explained.**
- Amadeus Self-Service was shut down on 17 July 2026; Kiwi Tequila, Skyscanner and direct GDS access
  need partner or agency contracts. Scraping booking sites is ruled out by their terms.
- Duffel (live mode) is the recommended primary source: priced, expiring offers with operating
  carrier, cabin, fare brand, baggage and taxes; China Southern and Virgin Australia reached via
  Travelport. Ignav as second source and for booking links; Travelpayouts (cached) for exploration
  only, always labelled Indicative.
- Virgin Australia's own Europe flights are operated by Qatar Airways via Doha, so they are excluded
  by the transit rule; "No practical fare found today" will be common for Virgin to Europe.
- Estimated running cost ≈ A$40–155 per month.
- This cloud session cannot reach api.duffel.com (network policy), so no live search could be run.

**Decided (pending owner confirmation).** Python FastAPI + worker, PostgreSQL job queue, Next.js
dashboard, Postmark or Resend; code ideally in its own repository. Egypt included in the excluded
transit list by default.

**Shipped.** Phase 1 report; milestone-1 probe script with transit check and unit tests.
No application build, version or release.

---

## 2. Definitions

- **Confirmed** — priced by an authorised API, repriced just before publishing, not expired.
- **Indicative** — a price that cannot be shown to be currently bookable (cached, unrepriced or
  unconfirmed); never used in purchase recommendations.
- **Expired / Unavailable / Rejected** — offer past its expiry / no longer returned on repricing /
  failed a verification rule (e.g. excluded transit).
- **Excluded transit** — any airport (segment endpoint or technical stop) in UAE, Qatar, Bahrain,
  Saudi Arabia, Oman, Kuwait, Jordan, Lebanon, Israel, Iran, Iraq, Syria, Yemen, Türkiye or Egypt.
- **Search link** — a URL that reproduces the route, dates and cabin, not the exact fare; labelled
  as such.
