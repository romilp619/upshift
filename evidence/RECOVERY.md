# Failure and recovery

Run `no-entire-1010-2157-4b95`, the `no-entire` arm — no Entire context, so this
is the agent's own verify-and-retry loop with nothing helping it.

Raw record: [`runs/no-entire-1010-2157-4b95.jsonl`](runs/no-entire-1010-2157-4b95.jsonl).
Console log: [`logs/run-no-entire.log`](logs/run-no-entire.log).

## The loop

Every patch is written to disk and then judged: re-import all 199 modules and
re-run the 62-test regression subset. It is kept only if importable modules
rise, failures blamed on that file fall, or tests pass that did not before —
and rolled back if importable modules or passing tests drop. On a rollback the
agent is re-prompted with the error its own patch produced.

## Recovered: `src/steamship/base/model.py`

```json
{"index": 3, "outcome": "migrated", "attempts": 3, "rollbacks": 2,
 "modules_importable": 165, "tests_passed": 23, "duration_s": 276.17}
```

Two patches written, verified, rejected and reverted; the third was kept and
took the package from 135 to **165 importable modules** and 12 to **23 passing
tests**. `base/model.py` is the shared base class every model in the codebase
inherits from, which is why one file moved the number by 30.

The commit history shows only the accepted version — the two rejected patches
never reached a commit:

```
1d2e895 upshift: migrate src/steamship/base/model.py to pydantic v2
04cebb9 codemod: bump-pydantic
62b3f96 Update README.md   ← the pinned starting point
```

## Gave up: `src/steamship/plugin/capabilities.py`

Four selections, three attempts each, twelve rollbacks, no improvement. The
agent never shipped a patch it could not justify — it quarantined the file and
moved on, and the run still finished at 199/199 modules and 57/62 tests.

This is the honest half of the result. The gate has no way to accept a change
that does not move a number, so an unfixable file costs time and nothing else.
Re-selecting it cost about 45 minutes, which is why later versions retire a file
whose blamed errors stop changing.

## Run totals

| | |
|---|---|
| Files acted on | 27 |
| Migrated | 21 |
| Quarantined | 4 (all `capabilities.py`) |
| Redirected to another file | 1 |
| **Rollbacks** | **15** |
| Modules importable | 31 → **199 / 199** |
| Green tests | 0 → **57 / 62** |
| Tokens | 179,297 in / 516,167 out |
| Cost | **$0.00** (deepseek-v4.1-flash free tier) |
| Wall clock | 62 minutes |

---

# Caught by Entire's review, not by us

After the migration finished at 199/199 modules and 61/62 tests, the 24 commits
were pushed to [Trail #1](https://entire.io/gh/romilp619/python-client/trails/1)
and Entire's `trail-review` runner evaluated the branch. It returned one
finding, **high severity, confidence 0.85**:

> This branch converts code across the repo to pydantic-v2-only APIs
> (ConfigDict, model_config, SerializeAsAny, model_dump_json/model_validate_json,
> model_fields, model_rebuild), but `requirements.txt` still pins
> `pydantic~=1.10.2` (and `requirements.dev.txt` likewise). `pyproject.toml`
> sources its dependencies dynamically from requirements.txt, so installing the
> package as declared will pull pydantic 1.x … breaking the whole package for
> any consumer who installs via the declared requirements.

It is correct, and our own gate could not have found it. The import probe runs
against a venv where pydantic 2.14 is already installed, so the package imports
cleanly no matter what the manifest declares. The metric was blind to the one
thing that breaks every downstream user.

Fixed in `5eee9f4` and resolved on the trail:

```
entire trail finding resolve 01M4MTPZXMFCCGW3CCX2EZNHZS \
  -m "Fixed in 5eee9f4: requirements.txt and requirements.dev.txt now pin pydantic>=2.9,<3."
→ open → resolved        Open findings: 0   Resolved: 1
```

The agent now does this itself: `MigrationAgent._bump_pins` reads the declared
pins from `requirements*.txt`, `pyproject.toml` and `setup.py` at the end of a
run and rewrites them to the target version. Migrating the code is not
migrating the project.
