# Upshift

**An autonomous framework-migration agent that finishes what codemods cannot — and gets cheaper per file as it learns the repository.**

Built for [neatHack 2026](https://neatlogs.com/hackathon).

---

## The problem

Framework migrations have official codemods. They are not enough.

We pointed `bump-pydantic` — the Pydantic team's own tool — at
[`steamship-core/python-client`](https://github.com/steamship-core/python-client),
a real repo with 198 modules pinned to `pydantic~=1.10.2`. It exited cleanly and
reported *"Refactored 11 files."*

The package still did not import:

```
src/steamship/data/package/package.py:19  class PackageCreateRequest
PydanticUserError: A non-annotated attribute was detected: `fetch_if_exists = False`.
All model fields require a type annotation.
```

`package.py` was not among the 11 files it touched. Codemods do mechanical
renames — `@validator` → `@field_validator`, `class Config` → `model_config`.
They cannot infer that `fetch_if_exists = False` should be
`fetch_if_exists: bool = False`, because that requires reading how the field is
used. That inference is the gap between a codemod and an agent, and it is the
whole reason this project exists.

## The benchmark

Two deterministic, full-coverage numbers — no self-grading:

1. **`modules_importable` / 198** — every `steamship.*` submodule imported in a
   fresh interpreter. Pydantic v2 rejects v1 model definitions at class-creation
   time, so this counts real progress rather than lines touched.
2. **`green_tests` / 62** — the 17 test files that pass offline under v1, used as
   a regression guard. Breaking one rejects the patch regardless of import count.

| Config | Files changed | Modules importable | Green tests |
|---|---|---|---|
| Pydantic v1 (reference ceiling) | — | **197 / 198** | **62 / 62** |
| v2, untouched source | 0 | **0 / 198** | **0 / 62** |
| v2, after `bump-pydantic` | 11 / 199 | **0 / 198** | **0 / 62** |
| v2, after Upshift | _see evidence/_ | _see evidence/_ | _see evidence/_ |

Reproduce the baseline: `python -m upshift baseline --target python-client`.
Raw evidence in [`bench/baseline-python-client.md`](bench/baseline-python-client.md)
and [`bench/bump-pydantic.patch`](bench/bump-pydantic.patch).

## How it works

Per file: ask Brain what we already decided here → ask Graph where the code
connects → migrate → checkpoint → verify → on failure roll back and retry →
on success write down what was learned.

```
          ┌─────────── Entire Brain ──────────┐
          │  what we already learned here     │
          ▼                                   │
   ┌──────────┐   ┌───────┐   ┌────────┐   ┌──┴───────┐
   │ Graph:   │──▶│ patch │──▶│ verify │──▶│ remember │
   │ where to │   └───────┘   └────┬───┘   └──────────┘
   │ look     │        ▲           │ fail
   └──────────┘        └───────────┘
                    Checkpoint rollback
```

Each tool earns its place, and we measure whether it does:

| Tool | Role | Not decorative because |
|---|---|---|
| **neatlogs** | traces every tool call, token and dollar | the learning curve below is read out of the traces |
| **Entire Graph** | finds call sites and blast radius before editing | ablation arm measures it |
| **Entire Brain** | remembers *this repo's* conventions across files | this is what makes later files cheaper |
| **Entire Checkpoints** | mechanical undo when verification fails | every rollback is a recorded checkpoint |
| **Entire Trails** | Runners review each batch; the agent fixes what they flag | verification the agent did not write |
| **cfo.ai** | pricing, costs, runway | see `BUSINESS.md` |

### The Brain effect

The agent learns a convention on file 3 — *"models here use `model_config`, not a
nested `class Config`"* — writes it with `entire brain remember`, and recalls it
on files 4–53. Cost per file falls as the run proceeds. That curve is the
headline result, and it is measured from neatlogs traces, not estimated.

### Ablation

Each Entire feature is a switch, so its contribution is a number rather than a claim:

```bash
python -m upshift run --target python-client --config no-entire
python -m upshift run --target python-client --config graph
python -m upshift run --target python-client --config graph+ckpt
python -m upshift run --target python-client --config graph+brain
python -m upshift report
```

## Quick start

```bash
git clone https://github.com/romilp619/upshift && cd upshift
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add NEATLOGS_API_KEY and a model key
entire login

python -m upshift setup    --target python-client   # clone, enable Entire, index Graph, build Brain
python -m upshift baseline --target python-client   # the codemod number to beat
python -m upshift run      --target python-client --config graph+brain
python -m upshift report
```

Any Anthropic-compatible gateway works — set `UPSHIFT_BASE_URL`. Claude-only
request features (adaptive thinking, effort, prompt caching) are sent only to
Claude models, so non-Claude gateway models do not 400.

## Layout

| Path | |
|---|---|
| `upshift/agent.py` | the migrate → verify → recover → remember loop |
| `upshift/entire_cli.py` | Graph, Brain, Checkpoints |
| `upshift/trails.py` | Trails + Runner findings |
| `upshift/guard.py` | rejects patches that fake success by deleting tests or assertions |
| `upshift/llm.py` | model client with token, cache and cost accounting |
| `upshift/obs.py` | neatlogs instrumentation |
| `bench/` | target spec and the codemod baseline |
| `evidence/runs/` | per-file JSONL — the learning curve |

## Honest notes

- The benchmark's green-test subset is 62 tests, not the full 266. The rest need
  the hosted Steamship API and are excluded as noise, not cherry-picked.
- A baseline of 0/198 looks flattering to us, so Upshift **runs `bump-pydantic`
  first and finishes what it cannot do**. The comparison is "codemod alone" vs
  "codemod + agent", which is the fair one.
