# Devlog (Building in Public)

This file tracks progress, decisions, tradeoffs, and lessons learned while building this project.

## DEVLOG vs NOTES (quick rule)

- Write in `DEVLOG.md` when the update is useful to future readers/collaborators.
- Write in `NOTES.md` when it is messy, temporary, private, or half-formed.
- Promote good ideas from `NOTES.md` into `DEVLOG.md` once they become real decisions.

## How to Use

For each entry, capture:

- what changed
- why it changed
- what was learned
- what is next

Keep it short and honest. One good paragraph is better than a long vague update.

---

## Entry Template

### YYYY-MM-DD — 

## **What changed**

## **Why**

## **Learnings**

## **Tradeoffs / risks**

## **Next**

---

## 2026-04-04 — Refactor foundation: service split

**What changed**

- Split a large state module into service-focused layers:
  - `DecisionService` for core bandit loop
  - `JourneyService` for multi-stage session/event flow
  - `AgentService` for observation/reasoning/orchestration
- Split API tests into domain files (`core`, `journey`, `agent`).

**Why**

- The original architecture grew from a simple single-task app into a larger journey/agent system, causing overlap and cognitive load.

**Learnings**

- Keeping service boundaries explicit makes both testing and reasoning about behavior much easier.
- Test files that mirror architecture are practical documentation.

**Tradeoffs / risks**

- More files means slightly more navigation overhead at first.
- Future drift can still happen unless boundaries are respected.

**Next**

- Keep `state.py` thin (wiring only).
- Continue centralizing shared constants/config to prevent subtle duplication.

---

## 2026-04-06 — Segment classifier: high intent vs new desktop direct

**What changed**

- Resolved overlap between `high_intent_search` and `new_desktop_direct` in `segments.classify()` by **narrowing** high intent (Path B: avoid merging segments or deleting a bucket).
- **Current rules (first-time visitors, after hint / returning / price-sensitive):**
  - **Mobile + paid** (`meta`, `google`, etc.) → `new_mobile_paid` (unchanged).
  - **Desktop + `google` or `organic`** → `high_intent_search`.
  - **Desktop + `direct` only** (typed direct traffic) → `new_desktop_direct` (no longer treats generic “organic” or empty/missing source as this bucket).
  - **Missing or unknown `traffic_source`** → `default` unless another rule applies.
- Updated `SEGMENT_DESCRIPTIONS` and `backend/tests/test_segments.py` to match.

**Why**

- The earlier broad high-intent predicate pulled in desktop direct/organic-style traffic that product-wise belonged in `new_desktop_direct`, causing inconsistent tests and ambiguous bandit arms.
- Splitting **search-like intent** (Google + organic on desktop) from **typed direct** keeps segments interpretable and testable.

**Learnings**

- Overlapping predicates plus “first match wins” order are easy to get wrong; unit tests for each segment and a “all segments reachable” check catch drift quickly.
- Empty string vs `"direct"` matters once rules are source-specific.

**Tradeoffs / risks**

- Organic SEO on **mobile** still falls through to `default` unless you add a rule later; that may or may not match product analytics.
- Any code or docs that assumed “empty source = direct” or “organic = new_desktop_direct” must stay in sync with `classify()`.

**Next**

- If the simulator or API clients send `traffic_source`, confirm they populate it consistently with these buckets.
- Optional: revisit mobile organic / empty source if analytics show a large `default` slice worth splitting.

---

## 2026-04-18 — Pivot: core bandit first, simulation as deliverable

**What changed**

- Reframed the repo around the **core contextual bandit** (`/decide`, `/feedback`, `/metrics`) and the **simulation workflow** (`make simulate`, `make plot`) as the main demo path.
- Moved journey-heavy docs and surfaces into a more clearly **advanced / experimental** role instead of presenting them as the default story.
- Recast the current agent loop as a **light orchestration / reporting sandbox** that can run simulated traffic and summarize experiments, without promising a full agent-first product.

**Why**

- The project risked drifting into a bigger journey platform than the original PoC needed.
- The strongest, most defensible deliverable is still the segmented Thompson-sampling loop plus the charts it produces.

**Learnings**

- A narrower product story is often stronger than a broader technical surface.
- The simulator and plots already communicate the value proposition better than the larger journey feature set.

**Tradeoffs / risks**

- The codebase still contains journey-specific internals under the agent sandbox, so the public story is simpler than the underlying architecture.
- Future readers need clear README / UI language so they do not assume the experimental journey pieces are the core deliverable.

**Next**

- Keep the core demo path frictionless and honest.
- Tighten the simulation artifacts so `demo_assets/` can serve as the canonical presentation output.

