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

From cfo.ai. Ari read the measured inference cost through the MCP connection —
it used the recorded **$0.00 free-tier cost per migration rather than an
estimate** — and built a live model in the workspace ("Migration runway",
Main Scenario) with customer-acquisition cohorts and an operating calendar,
not just a chat answer.

**Inputs given**

| | |
|---|---|
| Opening business cash | $0 |
| Founder monthly draw | $0 |
| CI | $10/month |
| neatlogs | $0 (free tier) |
| Entire | $0 for 6 months, then $200/month — an unverified placeholder; Entire's paid pricing is not public |
| Inference per migration | $0.00, measured |
| New customers | 1/month for 6 months, then 2/month |
| Repos per customer | 5 at landing, growing with the account |
| Pricing | $750 onboarding, $149/repo/month |

**Base forecast, October 2026 – September 2027**

| Month | Customers | Active repos | Subscription revenue | Cash costs |
|---|---|---|---|---|
| Oct 2026 | 1 | 5 | $745 | $10 |
| Nov 2026 | 2 | 10 | $1,490 | $10 |
| Dec 2026 | 3 | 16 | $2,384 | $10 |
| Jan 2027 | 4 | 23 | $3,427 | $10 |
| Feb 2027 | 5 | 31 | $4,619 | $10 |
| Mar 2027 | 6 | 40 | $5,960 | $10 |
| Apr 2027 | 8 | 55 | $8,195 | $210 |
| May 2027 | 10 | 71 | $10,579 | $210 |
| Jun 2027 | 12 | 89 | $13,261 | $210 |
| Jul 2027 | 14 | 109 | $16,241 | $210 |
| Aug 2027 | 16 | 131 | $19,519 | $210 |
| Sep 2027 | 18 | 155 | $23,095 | $210 |

**Break-even: October 2026 — the first month.** Ari separated two definitions
and both land in month 1:

- **Monthly cash break-even**, counting the $750 onboarding fee: the first
  customer alone covers it.
- **Recurring-only break-even**, where $149/repo/month must cover costs with no
  new sales: one customer on 5 repos is $745/month against $10 of cash cost.

In Ari's words, *"you do not need ongoing onboarding sales to cover these
modeled costs."* Month 1 generates about **$4,485 of net cash** against the
base-case $10 CI cost.

**There is no runway question in the usual sense.** With $0 opening cash, no
salary and essentially no fixed costs, the business cannot run out of money —
it is cash-positive from the first paying customer. The real risk is not
burn, it is whether anyone pays $750 at all.

**What this model assumes, and does not prove**

- The free inference tier stays available for all 12 months. Ari flagged this
  as an assumption rather than a guarantee, and it is the single largest
  unpriced risk: at list rates the cost becomes $2.26 per successful migration
  (section 5), which is still under 0.5% of a $750 price but no longer zero.
- Entire at $200/month is a placeholder.
- Zero churn, and no cost for human review of the agent's pull requests.
- Customer acquisition of 1–2 per month is an assumption with no evidence
  behind it. Nothing in this repository demonstrates demand; it demonstrates
  that the migration works.

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
4. **`cost_projection` was broken, then wrong, then optimistic.**
   - *Broken:* after (1) it read a key `unit_economics` no longer returned, so
     every call failed — over MCP, Ari received `Error executing tool
     cost_projection`.
   - *Wrong:* it priced a repository as a per-file median times an assumed file
     count, overstating per-repo cost by ~60%.
   - *Optimistic:* the first fix measured per-repo cost from every run that
     finished, calling each one "a repository migrated". That was false. A run
     can finish with tests still failing; of 11 finished runs only **3
     completed the migration** — every module importing and every regression
     test passing. The other 8 were incomplete.

   Successful and incomplete runs are now reported separately. As of the
   d041a87 ablation pass, 14 runs have finished:

   | claude-sonnet-5-5 | Per repo | 250 repos / month |
   |---|---|---|
   | Successful migration (n=6) | **$0.93** ($0.85 – $1.06) | **$232** if every run succeeds |
   | Incomplete run (n=8) | $0.95 ($0.74 – $1.51) | — |
   | Per success, paying for failed attempts (43% rate) | **$2.26** | **$566** at the observed rate |

   The observed rate is conservative: all 8 incomplete runs predate two
   harness fixes, and all 6 runs since them completed. Even at $2.26,
   inference is about 0.3% of a $750 price. These figures move as runs are
   added; the `cost_projection` tool always reports the current ones.

   Covered by `tests/test_mcp_server.py` (28 tests), including a regression
   test for a run that writes a summary but still has a failing test. Against
   the version that counted every finished run as a migration, 10 fail.

5. **The compounding-memory moat is not supported by our own measurement.**
   Section 3's third lever assumes that what the agent learns on one migration
   makes the next one cheaper and more reliable. Upshift tests exactly this
   with its `graph+memory` configuration: lessons from each accepted file are
   carried into later prompts. In the final ablation (commit `d041a87`, see
   the README) memory recalled 263 items and wrote 22, and changed **no**
   decision — the same files, in the same order, with the same outcome as no
   memory at all — while adding 87% more input tokens. On this benchmark it
   was overhead.

   That does not disprove the thesis across many customers and many
   migrations, which was not tested. But it means the moat in section 3 is a
   hypothesis, and the evidence in this repository does not back it. A pitch
   should lead with outcome-guaranteed delivery and the verify-and-roll-back
   loop, which the evidence does support, and not with accumulated learning.

