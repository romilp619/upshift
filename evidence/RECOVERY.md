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
