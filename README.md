# Upshift

**An autonomous migration agent that finishes what the official codemod can't.**

Point it at a Python repo stuck on Pydantic v1. It runs `bump-pydantic`, then
lets the interpreter tell it what is still broken, fixes the file that explains
the most failures, proves every edit against the whole package and a regression
suite, and rolls back anything that doesn't move the number.

Built for [neatHack 2026](https://neatlogs.com/hackathon) with **neatlogs**,
**Entire** and **cfo.ai**.

---

## The result

Target: [`steamship-core/python-client`](https://github.com/steamship-core/python-client) —
199 modules, pinned to `pydantic~=1.10.2`.

| | Modules importable | Green tests |
|---|---|---|
| Pydantic v1 — the ceiling | 198 / 199 | 62 / 62 |
| v2, untouched | 31 / 199 | 0 / 62 |
| v2 + `bump-pydantic` (official codemod) | **31 / 199** | 0 / 62 |
| v2 + `bump-pydantic` + **Upshift** | **RESULT_MODULES** | **RESULT_TESTS** |

The codemod exits cleanly, changes 11 files, and **gains zero modules**. It does
mechanical renames; it cannot decide that `fetch_if_exists = False` on a model
must become `fetch_if_exists: ClassVar[bool] = False` — that takes reading how
the attribute is used. That gap is the product.

How the metric works, and the baseline measurements:
[`bench/baseline-python-client.md`](bench/baseline-python-client.md).

## How it works

```
 bump-pydantic ──▶ import every module ──▶ blame each failure on a file
                          ▲                          │
                          │                          ▼
                   keep or roll back ◀── patch ◀── context
                   (imports must rise,          ├─ Entire Graph: definitions & callers
                    tests must not fall)        ├─ Entire search: related repo history
                                                └─ lessons learned earlier this run
```

1. **The interpreter drives the work.** Every module is imported in a fresh
   process; each failure is blamed on the deepest in-repo frame of its
   traceback, and the file that explains the most failures goes first. A regex
   over the source can't tell which file is breaking the build — a traceback can.
2. **The agent sees the error.** The failing traceback is in the first prompt.
   Without it, the model looked at a plausible file and returned it unchanged.
3. **Every edit is proven.** A patch is kept only if importable modules rise or
   failures blamed on that file fall — and never if importable modules or
   passing tests drop. Otherwise it is rolled back and the agent retries with the
   new error, up to three times.
4. **It can say "not here".** If the cause lives in another file — a base class,
   a shared model — the agent answers `NO_CHANGE_NEEDED: <path>` and the loop
   follows it.
5. **It remembers.** Each accepted file yields one repo-specific lesson, carried
   into later prompts and written into the commit as an `Upshift-Lesson:`
   trailer, where Entire search can find it on the next run.

## The three sponsor tools — and what each one actually does here

| | Role | Evidence |
|---|---|---|
| **neatlogs** | Every LLM call, import check, test run, Graph query and search is a span. Token counts and cost per file come from these traces. | traces tagged by config: NEATLOGS_LINKS |
| **Entire Graph** | Before each edit: the definitions, base classes and callers of the models in the file, plus the narrowest covering test. | 583 files, 2,118 symbols, 14,138 relations indexed |
| **Entire search** | Recall: related commits from the repo's history and from earlier Upshift runs. | finds e.g. a 2023 commit *"Fix pydantic validators"* |
| **Entire Trails** | The migration branch is a Trail; six runners (review, risk, security, drift, confidence, summary) evaluate each push. | TRAIL_LINK |
| **cfo.ai** | Ari is connected to the agent's telemetry over MCP and builds pricing and revenue from measured cost — and caught a 2× error in our own cost reporting. | [`BUSINESS.md`](BUSINESS.md) |

The chain matters more than any single tool: **Entire** tells the agent where
to look, **neatlogs** measures what each decision cost, and **cfo.ai** reads
those costs live and turns them into a business.

## Ablation: does each tool earn its place?

Same target, same model, same starting point. Only the context changes.

ABLATION_TABLE

Reproduce:

```bash
python -m upshift run --target python-client --config no-entire
python -m upshift run --target python-client --config graph
python -m upshift run --target python-client --config graph+memory
python -m upshift report
```

## Failure and recovery

Every rollback is recorded per file in `evidence/runs/*.jsonl` (`attempts`,
`rollbacks`). RECOVERY_EXAMPLE

## What broke along the way

The agent didn't work until it was measured honestly. Each of these would have
put a false number in front of you, and each was found by running it:

| Bug | Effect | Fix |
|---|---|---|
| A pytest collection crash parses as 0 failed / 0 errors | every file recorded as migrated against an empty diff | gate on the import probe, not on pytest alone |
| The import probe used `pkgutil.walk_packages` | one broken subpackage reported the whole package as 0/198 | import each module from disk independently |
| `entire graph search` called with a positional query | errored, returned `""` — Graph context never reached the agent | `--query`, `--format agent` |
| `.entire/` committed on the work branch | `reset --hard` deleted it; Entire went "not set up" mid-run | pin includes `.entire/`; restored on reset |
| Files worked alphabetically | correct edits rolled back for not being the current blocker | follow the traceback |
| The prompt never contained the error | the blocking file came back "no change" four times | traceback in the first attempt |
| Mean cost per file over 4 files, one 10k-token outlier | cost overstated ~2× — **caught by cfo.ai's Ari** | report the median |

## Quick start

```bash
git clone https://github.com/romilp619/upshift && cd upshift
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # NEATLOGS_API_KEY and a model key
ENTIRE_TOKEN_STORE=file entire login

python -m upshift setup    --target python-client
python -m upshift baseline --target python-client
python -m upshift run      --target python-client --config graph+memory
python -m upshift report
```

Any Anthropic-compatible endpoint works via `UPSHIFT_BASE_URL`; the runs here
used `deepseek-v4.1-flash` on the free tier through Token Harbor. Claude-only
request features (adaptive thinking, effort, prompt caching) are sent only to
Claude models.

To let cfo.ai read the telemetry:

```bash
python -m upshift.mcp_server --port 8787 --api-key <secret> --allow-host <tunnel-host>
```

## Layout

| Path | |
|---|---|
| `upshift/agent.py` | the loop: probe → blame → context → patch → verify → keep or roll back |
| `upshift/target.py` | the repo under migration: import probe, blame map, regression tests |
| `upshift/entire_cli.py` | Entire Graph and search |
| `upshift/trails.py` | Entire Trails and runner findings |
| `upshift/guard.py` | rejects patches that fake progress by deleting tests or assertions |
| `upshift/llm.py` | model client with token and cost accounting |
| `upshift/obs.py` | neatlogs instrumentation |
| `upshift/mcp_server.py` | the telemetry cfo.ai reads |
| `bench/` | target spec, baseline, codemod diff, Entire config |
| `evidence/runs/` | one JSONL per run: every file, attempt, rollback, token |

## Honest notes

- **Brain isn't used.** Entire documents a Brain memory feature, but it is not in
  CLI 0.11.4. Memory here is built from Entire search plus commit trailers.
- **One target repo.** The numbers are for one real codebase, not a benchmark
  suite.
- **One model measured.** All runs used `deepseek-v4.1-flash`. Costs for other
  models in `BUSINESS.md` are its measured token counts at list price.
- **62 of 266 tests.** The rest need the hosted Steamship API and can't run
  offline; they're excluded as noise, not cherry-picked.
