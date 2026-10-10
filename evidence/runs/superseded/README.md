# Superseded runs

Kept for the record, excluded from the results. Each was produced by a version
of the harness with a measurement or parsing bug that has since been fixed —
see "What broke along the way" in the top-level README.

| Runs | Why superseded |
|---|---|
| `no-entire-1010-14*` | the pytest-crash-reads-as-pass gate: files recorded as migrated against an empty diff |
| `graph+ckpt-1010-15*` | alphabetical ordering and no error in the prompt; also `entire graph search` was called wrongly, so Graph context never reached the agent |
| `graph+memory-1010-1536`, `-1540` | smoke and aborted runs while the probe was being fixed |
| `no-entire-1010-1542`, `graph-1010-1546` | the probe was correct, but pytest still aborted on collection errors, so every test count read 0 |
| `no-entire-1010-1554` | the fence extractor cut files containing ``` inside strings (react.py) |
| `no-entire-1010-1604` | valid harness; the process was killed by a session restart during phase 2, so it has no summary. Reached 199/199 modules, 60/62 tests. |
