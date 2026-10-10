# Ablation, first complete pass

Kept because the headline result stands: `no-entire` and `graph` both reached
**199/199 modules importable and 57/62 green tests** from a 31/199 start, at
$0.00.

Not used for the ablation *comparison*. Every arm ran with a fence-extraction
bug: the extractor read from the first opening fence to the last closing one,
so when the model appended an explanatory second code block the prose between
them was glued into the file. The guard rejected the result and the attempt
was rolled back — a harness fault counted against the agent. Since rollbacks
are the number the ablation compares (15 vs 9), the comparison was re-run on
the fixed extractor.

`graph+memory` was interrupted mid-run and is partial.
