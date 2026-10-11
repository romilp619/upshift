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

---

# Clean-room verification

The checks above run against the target's own venv, where pydantic 2.14 was
installed by hand. That proves the code migrated; it does not prove the
*package* did. So the result was reinstalled from scratch using only what it
declares.

```bash
git clone --no-local targets/python-client cleanenv   # no venv carried over
cd cleanenv && python3 -m venv .venv
.venv/bin/pip install -r requirements.txt             # declared deps only
.venv/bin/pip install -e . --no-deps
```

`pyproject.toml` takes its dependencies from `requirements.txt`
(`dependencies = { file = ["requirements.txt"] }`), which is exactly why the
stale pin mattered. With the agent's own `upshift: pin pydantic>=2.9,<3`
commit in place, the install resolves **pydantic 2.14.0**, and in that
untouched environment:

| | |
|---|---|
| Modules importable | **199 / 199** |
| Green tests | **61 passed, 1 failed, 0 errors** |

The pin fix was produced automatically by the run — `pins: updated
requirements.txt, requirements.dev.txt`, committed as the last of 23 commits,
with no manual step.

## The one remaining failure — and how it was fixed

`tests/steamship_tests/utils/test_static_instance_methods.py` —
`AttributeError: name`.

The test defines a model with a field and a `@staticmethod` of the same name,
and asserts both work:

```python
class CallableFoo(CamelModel):
    name: Optional[Callable[[Any], Any]]

    @staticmethod
    def name() -> str:
        return "static"

assert CallableFoo.name() == "static"     # the class-level staticmethod
assert callable_foo.name() == "instance"  # the per-instance value
```

Under v1 this worked: declared fields stayed ordinary class attributes, so the
`@staticmethod` remained reachable on the class. Under v2 the metaclass removes
field names from the class namespace and installs a `__getattr__` that raises
for anything that is not a private attribute:

```python
# pydantic/_internal/_model_construction.py
def __getattr__(self, item):
    private_attributes = self.__dict__.get('__private_attributes__')
    if private_attributes and item in private_attributes:
        return private_attributes[item]
    raise AttributeError(item)
```

```
is 'name' a declared field?       True
class attr 'name' in __dict__?    False
CallableFoo.name()             -> AttributeError: name
```

### Retraction

An earlier version of this file concluded that the only honest fixes were to
rename one of the two or delete the test, and that **"62/62 was never
reachable; 61 is the ceiling for a faithful migration."**

**That was wrong.** It was asserted from the mechanism without trying to work
around it. Codex reproduced the failure and made the unchanged test pass, and
the approach holds up.

### The fix

`__getattr__` on a metaclass is only consulted when normal attribute lookup
*fails*. Restoring a real class attribute means lookup succeeds and the
metaclass is never asked. The two subclass hooks fire either side of field
processing, which is exactly the window needed:

```python
class CamelModel(BaseModel):
    def __init_subclass__(cls, **kwargs):
        # still in the raw namespace: capture the colliding descriptors
        annotations = cls.__dict__.get("__annotations__", {}) or {}
        cls.__field_name_descriptors__ = {
            name: value
            for name, value in cls.__dict__.items()
            if name in annotations and isinstance(value, (staticmethod, classmethod))
        }
        super().__init_subclass__(**kwargs)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        # fields are built: put the descriptors back
        super().__pydantic_init_subclass__(**kwargs)
        for name, descriptor in cls.__dict__.get("__field_name_descriptors__", {}).items():
            setattr(cls, name, descriptor)
```

The field is untouched — it stays in `model_fields`, and instance access still
finds the per-instance value in `__dict__` first. Committed as `caab59f` on the
shared base class, so every model in the repo gets it.

### Verified

| | v1 reference | v2 + Upshift |
|---|---|---|
| Modules importable | 198 / 199 | **199 / 199** |
| Green subset | 62 / 62 | **62 / 62** |
| Wider offline suite | 74 passed, 97 failed, 95 errors | 74 passed, **96 failed**, 95 errors |

The wider suite is unchanged except for one fewer failure than the original v1
code; those ~190 failures need the hosted Steamship API and fail identically
under v1. The green subset now passes in full, in a clean room installed from
declared dependencies alone.

### Why the agent had not found it

Two harness faults, both exposed by an independent run that scored 56:

1. **The test phase ignored redirects.** When the agent answers
   `NO_CHANGE_NEEDED: <path>`, `migrate_file` pushes that path onto
   `self.redirects` — and the phase-2 loop picked files only by blame ranking
   and never read the list. In run `graph-1011-1356-94de`, four steps
   redirected to `plugin/outputs/plugin_output.py` and all four were dropped;
   it was fixed at step 29 only because it eventually surfaced in the ranking.
2. **This failure could not be blamed on any file.** Its only stack frames are
   the test file and pydantic internals, and the class it builds is defined in
   the test, so neither the deepest-`src`-frame rule nor the class-name lookup
   matched. `blame_tests` returned nothing, so the file was never picked and
   the agent never saw the error at all.

Fixed: phase 2 drains redirects before ranking, and an unattributable failure
is blamed on the first package module the failing test imports — here
`from steamship.base.model import CamelModel`, which is exactly the right file.

**The agent now derives this fix itself.** From the pinned commit, unaided:

```
start: 31/199 modules importable
codemod: 11 files changed -> 31/199
all modules import
all regression tests pass
pins: updated requirements.txt, requirements.dev.txt
final: 199/199 modules importable, 62 green tests passing
COMPLETE - every module imports and every regression test passes
```

Clean room, installed from declared dependencies alone: **199/199 modules,
62 passed, 0 failed, 0 errors.**

**Who found what.** Codex found the fix first, and the conclusion that no fix
existed was mine and was premature. What the agent lacked was not the idea but
the ability to see the failure: once redirects were followed and the failure
could be attributed to a file, it reached the same answer on its own.
