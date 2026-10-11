# Baseline: steamship-core/python-client, pydantic v1 → v2

Target pinned at `3bcc5d7` on the fork — upstream `62b3f96` plus `.entire/`
and nothing else, so the source is byte-identical to upstream.
Measured 2026-10-10.

## Metric

Two deterministic, full-coverage numbers:

1. **Modules importable / 199** — every `steamship.*` module, enumerated from
   disk and imported one at a time in a fresh, isolated interpreter. Pydantic v2
   rejects v1 model definitions at class-creation time, so this measures
   migration progress directly rather than lines touched.
2. **Green tests / 62** — the 17 test files that pass offline under v1, used as
   a regression guard. The other test files need the hosted Steamship API and
   are excluded as noise, not cherry-picked.

## Results

| State | Files changed | Modules importable | Green tests |
|---|---|---|---|
| Pydantic v1 (reference ceiling) | – | **198 / 199** | **62 / 62** |
| Pydantic v2, untouched source | 0 | **31 / 199** | 0 — suite cannot collect |
| Pydantic v2, after `bump-pydantic` | 11 | **31 / 199** | 0 — suite cannot collect |

**The official codemod changes 11 files and gains zero importable modules.**

It handles mechanical renames (`@validator` → `@field_validator`,
`class Config` → `model_config`) but not what needs inference — chiefly
un-annotated class attributes on models, which v2 rejects outright:

```
src/steamship/data/package/package.py, class PackageCreateRequest
PydanticUserError: A non-annotated attribute was detected: `fetch_if_exists = False`.
```

The right fix is `fetch_if_exists: ClassVar[bool] = False` — it is a class-level
flag, not a field — and deciding that requires reading how it is used.

Codemod diff: [`bump-pydantic.patch`](bump-pydantic.patch).

## Correction: an earlier version of this file said 0/198

The first probe walked the package with `pkgutil.walk_packages`, which only
swallows `ImportError`. Any other exception raised in a package `__init__` — a
`PydanticUserError`, for instance — terminates the walk, so a single broken
subpackage reported the **whole package** as 0 importable while 31 modules (and,
after three agent edits, 137) actually loaded.

The probe now enumerates modules from the filesystem and imports each one
independently. All numbers above were re-measured with it. The codemod still
gains nothing; the corrected baseline is 31, not 0.

## Entire CLI 0.11.4 — what is and is not available

`entire brain` is not in this CLI, and `entire plugin search brain` finds
nothing, so the documented Brain feature could not be used. The agent's memory
is built from what Entire does ship:

| Role | Implementation |
|---|---|
| Recall | `entire search "<error> <file>" --json --compact` — hybrid semantic + keyword search over the repo's commits, checkpoints and sessions. It indexes Upshift's own earlier commits as well as the repo's history, e.g. a 2023 commit titled *"Fix pydantic validators"*. |
| Remember | Each accepted file is committed with an `Upshift-Lesson:` trailer naming the repo-specific convention it learned. Later prompts in the same run see the lessons directly; future runs find them through `entire search`. |
| Locate | `entire graph search --query … --format agent` — Graph indexed 583 files, 2,118 symbols and 14,138 relations in 6.7 s. |
| Review | Entire Trails with six default runners, committed to the fork's default branch. |

Measured in the final ablation (commit `d041a87`): Graph context and the memory
built from search and lessons changed no decision on this benchmark and added
27% and 87% more input respectively. Trails is the Entire surface with a
verified effect - its review runner found a stale dependency pin.

## Environment note

The target's own venv needs `pip install --upgrade typing_extensions` after
installing requirements, or the pinned `aiosignal` fails to import
(`TypeVarTuple.__init__() got an unexpected keyword argument 'default'`).
