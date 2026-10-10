# cfo.ai input brief — Upshift

Paste this into cfo.ai (app.cfo.ai) and ask it to build pricing, cost structure,
revenue model and runway. Every number below is **measured**, not estimated —
sources in `bench/` and `evidence/runs/`.

---

## What the business sells

Upshift is an autonomous framework-migration agent. A customer points it at a
repository and a target migration (first product: Pydantic v1 → v2) and gets
back a branch with the migration done, verified, and reviewed.

The wedge is that official codemods do not finish the job. Measured on
`steamship-core/python-client` (199 modules, 54 files importing pydantic):

| | Modules importable | Green tests |
|---|---|---|
| Pydantic v1 (reference) | 198 / 199 | 62 / 62 |
| Untouched, under v2 | 31 / 199 | 0 / 62 |
| After `bump-pydantic` (the official codemod) | **31 / 199** | 0 / 62 |

The codemod exits successfully, changes 11 files, and gains zero importable
modules. It cannot infer that `fetch_if_exists = False` must become
`fetch_if_exists: ClassVar[bool] = False` — that needs reading how the field is
used. Upshift does that step.

## Measured unit economics

From the first runs, instrumented via neatlogs (superseded - query the `unit_economics` MCP tool for current median figures):

- **1,203 input tokens and 2,298 output tokens per file**

| Model | Cost / file | Cost / 54-file repo |
|---|---|---|
| deepseek-v4.1-flash (free tier) | $0.00000 | $0.00 |
| deepseek-v4.1-flash (paid) | $0.00130 | $0.07 |
| claude-sonnet-5-5 | $0.02538 | $1.37 |
| claude-opus-5-5 | $0.05076 | $2.74 |

Other COGS per migration: CI compute to run the test suite (the target's suite
runs in 14s; budget ~100 runs per migration), and Entire/Graph indexing (6.7s
for 583 files, one-off per repo).

**Direct cost to migrate a mid-size repository is under $3 even on the most
expensive model.**

## What the alternative costs the customer

- A contractor or consultancy quotes a framework migration in the low five
  figures.
- In-house: a senior engineer at a loaded cost of roughly $100/hour. A 54-file,
  198-module migration with test triage is conservatively 2–5 days of work,
  so **$1,600–$4,000 of engineering time**, plus the delay.
- Doing nothing has a cost too: staying on an EOL major version blocks
  dependency upgrades and accumulates security exposure.

## Questions for cfo.ai

1. **Pricing.** Per-repo one-off, per-seat subscription, or usage-based per file
   or per KLOC? Given COGS under $3 and a $1,600–$4,000 alternative, where
   does price land without leaving obvious money on the table or stalling
   adoption?
2. **Gross margin** at each pricing model, including CI and inference.
3. **Revenue model.** One migration per customer is inherently one-off. What
   makes it recurring — a catalogue of migrations (Pydantic, SQLAlchemy 2.0,
   React 19, CJS→ESM), or continuous dependency upkeep as a subscription?
4. **Runway.** Solo founder, no salary for 6 months. Costs are inference,
   CI, and the Entire/neatlogs tiers. What does 12 months look like, and what
   monthly revenue reaches break-even?
5. **Go-to-market.** Who buys: the platform team at a 50–200 engineer company,
   or an agency doing migrations for clients?
6. **Risk.** Model providers could ship this as a feature. What is the moat —
   the verification harness and accumulated per-repo memory, or something else?

## Facts to hand cfo.ai if it asks

- Stage: prototype, built during a 48-hour hackathon, not yet launched
- Team: 1 (solo)
- Current revenue: $0
- Current burn: effectively $0 (running on a free inference tier)
- Target market: Python and JavaScript teams on EOL major versions
- Proof point: works, with measured before/after numbers against the official codemod
