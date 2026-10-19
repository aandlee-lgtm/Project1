# Sydney Flight Intelligence — feature backlog

Requests from the owner, recorded as features. Nothing here is built, versioned or released until
the owner's message includes **build_new**.

| # | Requested | Feature | Status |
|---|---|---|---|
| F1 | 2026-10-19 | **Phase 1 — provider feasibility and architecture.** Compare flight-data providers (coverage of AU market, China Southern, Virgin Australia and partners, long-range search, return pricing, cabin/booking class, taxes, baggage, expiry/repricing, booking links, cost, terms); recommend an architecture; identify risks; estimate monthly cost. | Done (report: [PHASE1_PROVIDER_FEASIBILITY.md](PHASE1_PROVIDER_FEASIBILITY.md)) |
| F2 | 2026-10-19 | **Milestone 1 — one live SYD return itinerary.** A real, currently priced return itinerary with dates, operating carrier, total A$ and a booking path, from an authorised API; transit through the Middle East / Turkey rejected; offer repriced before display. | Planned — probe written (`flight-intel/probe/live_search.py`); waiting for a Duffel live token and network access |
| F3 | 2026-10-19 | **Phase 2 — data pipeline.** Provider abstraction (Duffel, Ignav, Travelpayouts), normalisation, verification stages A–E and states (Confirmed / Indicative / Expired / Unavailable / Rejected), PostgreSQL history, layered search with call budgets, mandatory China Southern and Virgin Australia assessment ("No practical fare found today" when none). | Planned (after F2) |
| F4 | 2026-10-19 | **Phase 3 — deal intelligence.** 0–100 score with configurable weights (price 35, routing/time 20, dates 15, inclusions 10, loyalty 10, confidence 10), labels only for verified offers, explanations, premium-cabin comparison, comparable-cohort history (7/30 days, distributions, seasonality), loyalty assessment (Velocity, Sky Pearl) only when fare class supports it, schema-validated AI summaries from database rows. | Planned |
| F5 | 2026-10-19 | **Phase 4 — dashboard.** Next.js views: Dashboard, Flight explorer, Fare history, Watchlist, Loyalty settings, Notification centre, Administration and diagnostics. | Planned |
| F6 | 2026-10-19 | **Phase 5 — email.** Two separate sends (leeawc@me.com, Rhianhughes@me.com), subject `Agent: Best flights - <Sydney date>`, inline-CSS HTML with both tables + plain text, `View fare` links, per-recipient state, retries with backoff, no retries on permanent errors, duplicate prevention, delivery webhooks. | Planned |
| F7 | 2026-10-19 | **Phase 6 — production readiness.** Unit, integration and end-to-end tests (mocked data clearly separate from live acceptance tests), security, monitoring, Docker, deployment guide, env template, troubleshooting guide. | Planned |
