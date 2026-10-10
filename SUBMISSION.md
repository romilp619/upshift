# neatHack submission pack

Everything needed to submit, in order. Numbers marked `«…»` are filled from the
final ablation run.

---

## 1. Evidence checklist (mapped to the judging rules)

| Rule | Where | Status |
|---|---|---|
| **The agent improved** — a run before a change and after, with numbers | Ablation table in `README.md`; `evidence/runs/no-entire-*.jsonl` vs `graph+memory-*.jsonl`; one neatlogs trace per arm | after ablation |
| **You used neatlogs** — trace links or screenshots | neatlogs → Traces, filter by tag `no-entire` / `graph` / `graph+memory` | **you: screenshot** |
| **You used Entire** — checkpoints or entire-graph output | Graph index stats in `bench/baseline-python-client.md`; Trail on `romilp619/python-client`; `entire search` recall | done |
| **You used cfo.ai** — pricing, costs, revenue, runway | `BUSINESS.md` (cost, pricing, recurring revenue from Ari over MCP) | **you: ask Ari for runway** |
| **The agent recovers from failures** | `evidence/runs/*.jsonl` — `rollbacks > 0` then `outcome: migrated`, e.g. `plugin/capabilities.py` | done |
| **You built in public** — links tagged #neatHack | posts below | **you: post** |
| **Code written during the hackathon** — public repo, dated commits | https://github.com/romilp619/upshift | done |

---

## 2. Demo video — 3 minutes

Record the screen; talk over it. Keep each shot short.

**0:00–0:20 — The problem.**
Show `bench/baseline-python-client.md`.
> "Pydantic v2 broke every v1 codebase. The official fix is a codemod. On this
> real repo — 199 modules — it changes 11 files and the number of modules that
> import goes from 31 to… 31. Zero."

**0:20–0:40 — Why.**
Show the `fetch_if_exists = False` error, then the agent's diff to
`ClassVar[bool] = False`.
> "A codemod renames things. It can't decide this is a class constant and not a
> field. That takes reading the code. That's what Upshift does."

**0:40–1:30 — The agent running.** Terminal with `python -m upshift run`.
> "It imports every module, blames each failure on a file using the traceback,
> and fixes the one that explains the most failures first. Watch the number:
> 31… 116 from one file… 135… «final»."
Point at one line with `rb=1`:
> "Here an edit didn't move the number. It was rolled back automatically, the
> agent got the new error, and fixed it on the second try. Nothing is kept
> unless the whole package proves it."

**1:30–2:10 — neatlogs and Entire.**
neatlogs trace for the run → expand one file: LLM call, import check, Graph
query, test run.
> "Every step is a span in neatlogs — that's where the cost per file comes from."
Entire: the Trail on the migration branch; Graph output in the prompt.
> "Entire Graph tells it where a model is defined and who calls it. Entire
> search finds related history — including lessons it wrote on earlier runs."
Ablation table:
> "And we measured whether each tool earns its place: «no-entire vs graph+memory»."

**2:10–2:45 — cfo.ai.**
Ari answering over MCP.
> "cfo.ai is connected to the agent's live telemetry over MCP. It priced this at
> $750 per repo, outcome-guaranteed, with a $149 per repo per month subscription
> to keep code current — and it caught a 2× error in our own cost numbers."

**2:45–3:00 — Close.**
> "Entire tells the agent where to look. neatlogs measures what each decision
> cost. cfo.ai turns that into a business. Upshift — migrations that finish."

---

## 3. Posts — paste as-is, add a screenshot to each

**Post 1 — the hook** (screenshot: the baseline table)
> Pydantic's official codemod on a real 199-module repo: changes 11 files, exits
> clean. Modules that import before: 31. After: 31.
>
> Building an agent that finishes the job for #neatHack 🧵

**Post 2 — the one line** (screenshot: the `ClassVar` diff)
> The line the codemod can't write:
>
> `fetch_if_exists = False` → `fetch_if_exists: ClassVar[bool] = False`
>
> It's not a field, it's a class flag. Knowing that means reading the code. One
> file, +85 modules importing. #neatHack

**Post 3 — the bug the agent taught me** (screenshot: the "same" lines)
> My agent kept returning the file that was breaking the build with "no changes
> needed". Four times.
>
> I'd never shown it the error. One line in the prompt fixed it. #neatHack

**Post 4 — cfo.ai** (screenshot: Ari's reply)
> Wired @cfo_ai to my agent's telemetry over MCP so the business plan reads real
> cost per migration.
>
> First thing it did: catch a 2× error in my own unit economics. #neatHack

**Post 5 — the result** (screenshot: final numbers + ablation table)
> Final: codemod 31/199 → Upshift «N»/199 modules importing, «T»/62 tests
> green, «$» in inference.
>
> Traced with @neatlogs, context from @EntireHQ Graph + search, priced with
> @cfo_ai. #neatHack

---

## 4. Submission — quote the official neatlogs post on X

> **Team:** «team name»
> **Project:** Upshift — an agent that finishes migrations the official codemod can't
> **Repo:** https://github.com/romilp619/upshift
> **Demo:** «video link»
>
> Codemod: 31/199 modules. Upshift: «N»/199. #neatHack

Window: **Monday 12 October, 7:00–11:55 PM IST.** neatlogs and cfo.ai engage
with the first 50 quote posts — submit early in the window.

Before submitting: check the handles above (`@neatlogs`, `@EntireHQ`,
`@cfo_ai`) against the real accounts — they are guesses.
