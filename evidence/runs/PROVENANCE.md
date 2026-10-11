# Run provenance

Runs from before the harness recorded its own version. From commit `e276718`
on, every run summary carries `harness: <commit>[-dirty]`; for these, the
version is inferred from timestamps against `git log` and stated as inferred.

| Run | Outcome | Started | Harness (inferred) | Notes |
|---|---|---|---|---|
| `no-entire-1011-1119-1c17` | incomplete 61/62 | 11:19 | pre-`eb61d4a` | ablation pass |
| `graph-1011-1126-fe10` | incomplete 61/62 | 11:26 | pre-`eb61d4a` | ablation pass |
| `graph+memory-1011-1134-80df` | incomplete 55/62 | 11:34 | pre-`eb61d4a` | ablation pass |
| `graph-1011-1150-bd44` | incomplete 61/62 | 11:50 | pre-`eb61d4a` | |
| `graph-1011-1218-3f5a` | incomplete 61/62 | 12:18 | pre-`eb61d4a` | |
| `graph-1011-1225-6dbd` | incomplete 61/62 | 12:25 | pre-`eb61d4a` | |
| `graph-1011-1356-94de` | incomplete 56/62 | 13:56 | pre-`eb61d4a` | run by Romil; exposed the ignored redirects |
| `graph-1011-1423-cb74` | incomplete 61/62 | 14:23 | `eb61d4a` (redirects fixed) | blame fix not yet made |
| `graph-1011-1431-ee3c` | **complete 62/62** | 14:31 | `eb61d4a` **+ uncommitted** blame fix | `--no-codemod` |
| `graph-1011-1438-aa24` | **complete 62/62** | 14:38 | `eb61d4a` **+ uncommitted** blame fix | |
| `graph-1011-1454-6bde` | **complete 62/62** | 14:54 | **`84fb3c5`, clean** | not started from the session that built Upshift; most likely the independent verification run. The only successful run tied to committed code. |

`84fb3c5` was committed at 14:48 and no file under `upshift/` changed again
until 21:45, so `graph-1011-1454-6bde` ran on exactly that commit.

Two of the three successful runs therefore used code that did not exist in the
repository when they ran. They are kept because the fix they used is the one
that was then committed unchanged, but the run that best supports the headline
is `graph-1011-1454-6bde`.
