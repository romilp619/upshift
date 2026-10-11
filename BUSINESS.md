# Upshift — business plan

Produced with **cfo.ai**. Ari, cfo.ai's AI CFO, was connected to Upshift's own
telemetry over MCP (`upshift.mcp_server`, five read-only tools) and answered from
the agent's measured run data rather than from estimates. Ari's answers are
reproduced below, lightly formatted. Section 5 records what has changed since.

Inputs given to Ari: [`BUSINESS-INPUTS.md`](BUSINESS-INPUTS.md) and the live
`upshift-telemetry` MCP server (`unit_economics`, `cost_projection`,
`list_runs`, `run_detail`, `migration_results`).

---

## 1. Cost per migration

> *"What does it cost us to migrate one repository, and what would 250
> migrations per month cost at each model tier?"*

The AI cost is tiny. What you charge should depend on what the work is worth to
the customer, not on your cost.

| Model | Per file | Per repo (54 files) | 250 repos / month | Per year |
|---|---|---|---|---|
| DeepSeek Flash (free) | $0 | $0 | $0 | $0 |
| DeepSeek Flash | $0.0013 | $0.07 | $17.58 | $211 |
| Claude Sonnet | $0.025 | $1.37 | $342.64 | $4,112 |
| Claude Opus | $0.051 | $2.74 | $685.29 | $8,223 |

Not included: CI compute, the Entire and neatlogs subscriptions, retries on
failed files, human review, and salaries.

## 2. Pricing

What the customer pays otherwise:

- **In-house engineer:** $1,600–4,000 (2–5 days at about $100/hour)
- **Contractor:** low five figures

**Recommendation: $750 per repo, flat, up to ~200 files — charged only when the
result imports and the tests pass.** Larger repos at $1,500 up to ~600 files.

- An easy yes: under half the cheapest alternative, and the customer only pays
  for a working result.
- Margin holds: even on Opus plus an hour of human review (~$100), about 85%
  gross margin; without review about 99%.
- Use the strongest model. Its extra cost is a few dollars a repo; one failed
  migration costs more in trust than a year of the price difference.
- Not lower: $50–100 would still be profitable but reads as a cheap script
  rather than days of engineering saved. Easier to cut a price than raise it.

At 250 repos a month, $750 each is about **$187k/month revenue against ~$2.5k
of inference**.

## 3. Making it recurring

> *"A migration is a one-off purchase. What makes this recurring revenue?"*

One-off migrations are services revenue, and investors value them that way. For
revenue to recur, the customer needs a problem that keeps coming back — and
theirs does.

**The recurring problem: code keeps going out of date.** Pydantic v1→v2 is one
example of something that never stops: SQLAlchemy 2.0, NumPy 2, Django releases,
Python versions retiring features, cloud SDKs, LangChain changing interfaces
every quarter. Every repo falls further behind each month, and today the
customer pays for that in engineer-days, several times a year, on every repo.

So the product isn't *"migrate my repo."* It's **"my repos never fall behind."**

Three ways to make it recur, strongest first:

1. **Per-repo subscription to keep code current** — the agent watches each
   repo's dependencies and, when an upstream library ships a breaking release,
   opens a pull request with the migration done and tests passing. A repo needs
   perhaps 4–8 migration-sized jobs a year; on Opus that is under $1 of
   inference a month, so gross margin stays above 90% even with review.
   Expansion is built in: companies have 50–500 repos.
2. **Gating upgrades in CI** — on every PR or on a schedule: "this change will
   break when you move to X, and here's the fix." Puts Upshift in the daily
   workflow; bundles with (1).
3. **A library of migrations that compounds** — every migration teaches the
   system something about that library change. The tenth customer's SQLAlchemy
   migration should be cheaper and more reliable than the first. That is the
   moat against a customer running a model themselves.

| Tier | Price | Includes |
|---|---|---|
| Onboarding | $750/repo, one-time | First major migration, outcome-guaranteed |
| Keep-current | $149/repo/month | Every breaking upgrade, delivered as passing PRs |
| Enterprise | ~$5k+/month | 50+ repos, CI gating, priority library coverage |

A customer with 40 repos on Keep-current is about **$71k/year recurring**,
against $30k for one migration per repo.

**Risks Ari flagged**

- **Delivery first.** A subscription to something that doesn't produce a
  working repo just churns faster.
- **Single-migration trap.** If Pydantic is the only use case, the market
  disappears once the world has moved to v2. The subscription only works with
  coverage of the next 5–10 breaking upgrades.
- **Measure:** migrations per repo per year, net revenue retention (target
  >120% as customers add repos), and the share of agent PRs that merge without
  human edits.

## 4. Runway

**Not yet from cfo.ai — Ari's answers above cover cost, pricing and recurring
revenue, but not runway.** To be replaced with Ari's answer to:

> *"Model 12 months of runway. Solo founder, no salary for the first 6 months,
> $0 revenue today, running on a free inference tier. Costs are inference
> (use unit_economics), CI, and the Entire and neatlogs subscriptions. Using
> your $750 onboarding and $149/repo/month Keep-current pricing, how many
> customers and repos reach break-even, and in which month?"*

## 5. What has changed since Ari answered

Ari's analysis is above as given. Three of its inputs have since been corrected —
two of them because Ari itself raised them:

1. **Cost per file was overstated ~2×.** Ari noticed the summary claimed 2,298
   output tokens per file while the visible rows averaged ~880. It was right: one
   file used 10,779 output tokens and dragged the mean. The MCP tool now reports
   the **median**, which puts Sonnet at about **$0.014 per file**, not $0.025.
   Every conclusion above gets stronger, not weaker.
2. **Per-repo denominator.** Section 1 assumes 54 files per repo — the files that
   import pydantic. Ari later scaled to 198, the module count. The work is
   driven by failing modules rather than a file count, so real per-repo cost is
   what the run logs say; see `evidence/runs/`.
3. **"The agent hasn't delivered a working result yet."** When Ari answered, the
   agent was reported at 0/198 importable. That number came from a broken
   measurement probe (see `bench/baseline-python-client.md`). The honest
   baseline is **31/199**, the codemod leaves it at **31/199**, and the agent's
   result is in the README and `evidence/`.
4. **`cost_projection` was broken, then wrong.** After (1), the tool read a key
   `unit_economics` no longer returned, so every call failed — over MCP, Ari
   received `Error executing tool cost_projection`. Separately it priced a
   repository as a per-file median times an assumed file count, overstating
   per-repo cost by ~60%. A completed run *is* one repository migrated, so
   per-repo cost is now measured directly from 11 complete runs:

   | Model | Per repo (median) | Range | 250 repos / month |
   |---|---|---|---|
   | claude-sonnet-5-5 | **$0.94** | $0.74 – $1.51 | **$235** |
   | claude-opus-5-5 | **$1.88** | $1.49 – $3.03 | **$470** |

   Lower than section 1's figures, so the pricing conclusions hold with more
   margin. Covered by `tests/test_mcp_server.py` (19 tests, including real
   JSON-RPC calls over HTTP with the API key); 11 of them fail on the broken
   version.

