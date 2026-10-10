# Baseline: steamship-core/python-client, pydantic v1 -> v2

Measured 2026-10-10. Commit `62b3f9659fd43ce4fe62103b6488514259d1956f`.
Reproduce with `python -m upshift baseline --target python-client`.

## Metric

Two numbers, both deterministic and full-coverage:

1. **`modules_importable` / 198** - every `steamship.*` submodule, imported in a
   fresh interpreter. Pydantic v2 rejects v1 model definitions at class-creation
   time, so this counts real migration progress rather than lines touched.
2. **`green_tests` / 62** - the 17 test files that pass offline under v1.
   A regression guard: breaking one of these rejects the patch no matter what
   the import count says.

## Results

| Config | Files changed | Modules importable | Green tests |
|---|---|---|---|
| Pydantic v1 (reference) | - | **197 / 198** | **62 / 62** |
| Pydantic v2, untouched source | 0 | **0 / 198** | **0 / 62** |
| Pydantic v2, after `bump-pydantic` | 11 / 199 | **0 / 198** | **0 / 62** |
| Pydantic v2, after Upshift | _TBD_ | _TBD_ | _TBD_ |

## Why the codemod scores zero

`bump-pydantic` ran clean (exit 0, "Refactored 11 files") but the package still
fails on the very first model it loads:

```
src/steamship/data/package/package.py:19, class PackageCreateRequest
pydantic.errors.PydanticUserError: A non-annotated attribute was detected:
`fetch_if_exists = False`. All model fields require a type annotation.
```

`package.py` is not among the 11 files it touched. The codemod handles mechanical
renames - `@validator` -> `@field_validator`, `class Config` -> `model_config` - but
not un-annotated class attributes, which need a type inferred from how the field is
actually used. That inference is the part a coding agent can do and a codemod cannot.

Files the codemod did change:
agents/mixins/transports/slack.py, agents/schema/action.py, agents/schema/functions.py,
agents/tools/classification/multiple_choice_tool.py, agents/tools/search/search.py,
base/model.py, data/manifest.py, invocable/invocable.py, invocable/invocable_response.py,
plugin/capabilities.py, plugin/request.py

Full diff: `bench/bump-pydantic.patch`.

## Environment note

The target's own venv (`targets/python-client/.venv`) needs
`pip install --upgrade typing_extensions` after installing requirements -
the pinned `aiosignal` fails to import otherwise
(`TypeVarTuple.__init__() got an unexpected keyword argument 'default'`).

## Entire CLI 0.11.4 — what is actually available

`entire brain` does not exist in this CLI and `entire plugin search brain`
returns nothing. The documented Brain feature is not shipped here, so the
repo-memory role is filled by checkpoints plus `entire search`:

| Documented as | Actually used |
|---|---|
| `brain brief` / `brain recall` | `entire search "<task>" --compact` — hybrid semantic + keyword over checkpoints, sessions and commits, scoped to the repo. `--compact` is explicitly shaped for agents. |
| `brain remember` | committing. Entire captures the session as a checkpoint linked to the commit, which `search` then indexes. |
| `brain setup` | `entire enable` + `entire graph index`. |

This is arguably the better story: checkpoints are Entire's core product and
need no feature flag, whereas Brain is unavailable.

Already proven useful — searching the untouched target returns a 2023 commit
from its own history titled *"Fix pydantic validators"*, real prior art for the
migration.

Custom agents are not captured by hooks (Entire ships hooks for claude-code,
codex, cursor, copilot-cli and others). `entire session attach` creates a
checkpoint from a transcript for "any registered agent, including external
agents enabled via external_agents in .entire/settings.local.json" — that is
the route for Upshift to write its own checkpoints.

Graph indexed the target: 583 files, 582 parsed, 2118 symbols, 14138 relations
in 6.7s.
