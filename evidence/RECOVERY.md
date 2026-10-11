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

## The one remaining failure

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

Under pydantic v1 this worked: fields stayed ordinary class attributes, so the
`@staticmethod` named `name` remained reachable on the class.

Under v2 it cannot. The metaclass removes declared fields from the class
namespace and installs a `__getattr__` that raises for anything that is not a
private attribute:

```python
# pydantic/_internal/_model_construction.py
def __getattr__(self, item):
    private_attributes = self.__dict__.get('__private_attributes__')
    if private_attributes and item in private_attributes:
        return private_attributes[item]
    raise AttributeError(item)
```

Reproduced directly:

```
is 'name' a declared field?       True
class attr 'name' in __dict__?    False
CallableFoo.name()             -> AttributeError: name
```

So the field declaration wins and the staticmethod is gone from the class.
This is not an incomplete migration — it is a v1 behaviour v2 deliberately
removed. The only honest fixes are to rename one of the two, or drop the test,
and both change the library's public surface. The agent is explicitly
instructed never to delete a test or weaken an assertion to make a suite pass,
so it left it alone and quarantined the file.

**62/62 was never reachable.** The ceiling for a faithful migration of this
repo is 61, and the agent reaches it.
