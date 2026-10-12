# neatHack submission pack

Every claim in this file is a verified finding with a pointer to its evidence.
Nothing here says Entire Graph or memory improved the benchmark — the final
ablation measured that they did not.

---

## 1. Evidence checklist (mapped to the judging rules)

| Rule | Evidence | Status |
|---|---|---|
| **The agent improved** — a run before a change and after, with numbers | One change, everything else held: Haiku, `graph`, start 31/199. **Before** the harness fix, `graph-1011-1356-94de`: 56/62 tests, incomplete, 29 steps, 7 redirects ignored. **After**, `graph-1011-1454-6bde`: **62/62, complete**, 23 steps, 1 redirect followed. Both in `evidence/runs/`; provenance in `evidence/runs/PROVENANCE.md`. | done |
| **You used neatlogs** — trace links or screenshots | The two runs above (11 Oct, ~13:56 and ~14:54 IST, tag `graph`) and the final ablation pass (11 Oct, 22:12 / 22:20 / 22:28, tags `no-entire` / `graph` / `graph+memory`) | **you: screenshot** |
| **You used Entire** — checkpoints or entire-graph output | Trail #1 on `romilp619/python-client`, where the review runner raised a high-severity finding that was fixed and resolved; Graph index (583 files, 2,118 symbols, 14,138 relations); 24-commit migration branch | done |
| **You used cfo.ai** — pricing, costs, revenue, runway | `BUSINESS.md` — cost, pricing, recurring revenue and a 12-month runway model, all from Ari over MCP, plus five recorded corrections. Ari built a live model in the cfo.ai workspace from the measured $0.00 inference cost. | done |
| **The agent recovers from failures** | `evidence/RECOVERY.md`: `base/model.py` rolled back once then kept (+30 modules); the Trails finding that led the agent to fix dependency pins itself | done |
| **You built in public** — links tagged #neatHack | posts below | **you: post** |
| **Code written during the hackathon** — public repo, dated commits | https://github.com/romilp619/upshift | done |

---

## 1b. End-of-project steps — before Monday 7 PM IST

Entire's job, in the organisers' words, is *"records every session"*: the
Claude Code session that built Upshift should be a checkpoint on this repo. It
is deliberately **not** enabled yet — the session transcript contains live keys
in plaintext, and Entire syncs checkpoints to `origin`, which is public.

1. **You:** revoke the GitHub PAT; rotate the Token Harbor and neatlogs keys;
   put the new ones in `.env`.
2. **Claude:** rotate the MCP API key and restart the server (update it in
   cfo.ai → MCP → DEMOMCP).
3. **Claude:** `entire enable -y --agent claude-code` in `~/neathack`, attach
   this session with `entire session attach <session-id>`, push.
4. Check the checkpoint is visible on entire.io for `romilp619/upshift`.
5. Terminate the AWS instance after the demo is recorded — one instance per
   user is allowed. See [`DEPLOY.md`](DEPLOY.md).

---

## 2. Verified findings — the only claims the demo makes

| # | Finding | Evidence |
|---|---|---|
| 1 | The official codemod changes 11 files and gains **zero** importable modules: 31/199 before and after. | `upshift baseline`; `bench/baseline-python-client.md` |
| 2 | Upshift takes the same repo from **31/199 to 199/199 modules and 0 to 62/62 tests**, prints `COMPLETE`, exits 0. | final ablation, `evidence/ablations/20261011-2212-d041a87/` |
| 3 | Installed fresh from its own declared dependencies, the result still passes: **199/199, 62/62**. | `evidence/RECOVERY.md`, clean-room section |
| 4 | **6 of 14** finished runs completed the migration; **6 of 6** since two harness fixes. Small sample. | `upshift report`; `evidence/runs/PROVENANCE.md` |
| 5 | Edits that don't improve the numbers are rolled back automatically and retried. | `evidence/RECOVERY.md` |
| 6 | Entire's Trails review runner found a high-severity bug the agent's own checks could not see — a stale `pydantic~=1.10.2` pin. The agent now fixes pins itself. | Trail #1; `evidence/RECOVERY.md` |
| 7 | **Entire Graph and memory changed nothing on this benchmark.** All three arms: same files, same order, same outcome; 27% and 87% more input. | README ablation |
| 8 | cfo.ai, reading the agent's telemetry over MCP, caught a 2× error in our own cost reporting. | `BUSINESS.md` §5 |
| 9 | Sonnet-list cost: **$0.93** per successful migration, **$2.26** counting failed attempts. Actual: $0.00 on a free tier. | `cost_projection` over MCP; `BUSINESS.md` §5 |
| 10 | The last failing test's fix was found first by another agent (Codex). After two harness fixes, Upshift derives it unaided. | README honest notes |

---

## 3. Demo video — 3 minutes

Record the screen; talk over it. Every line maps to a finding above.

**0:00–0:20 — The problem.** *(finding 1)*
Run `upshift baseline`.
> "Pydantic v2 broke every v1 codebase. The official fix is a codemod. On this
> real repo — 199 modules — it changes 11 files, and the number of modules that
> import goes from 31 to 31."

**0:20–0:40 — Why.**
The `fetch_if_exists = False` error, then the agent's `ClassVar[bool]` diff.
> "A codemod renames things. It can't tell this is a class flag rather than a
> field. That takes reading the code."

**0:40–1:25 — The agent running.** *(findings 2, 5)*
`upshift run --target python-client --config no-entire`, sped up. Stop on:
- a `->` line: *"Here it worked out the real cause was in a different file, and
  went there instead."*
- the `final` / `COMPLETE` lines: *"199 of 199 modules, 62 of 62 tests."*
> "Every edit is checked against the whole package and the test suite. If the
> numbers don't improve, the edit is rolled back and it tries again with the new
> error."
Show `evidence/logs/deepseek/run-no-entire.log`, the `base/model.py` line with
`att=2 rb=1`: *"Here: rejected once, kept the second time, 30 more modules."*

**1:25–1:55 — Is it real?** *(findings 3, 6)*
> "Then we installed it fresh, from its own declared dependencies only. Still
> 199 and 62."
Trail #1 on entire.io, the resolved finding:
> "And Entire's review runner caught something our checks couldn't: the code was
> migrated but `requirements.txt` still said pydantic 1. Anyone installing it
> would have got a broken package. The agent fixes that itself now."

**1:55–2:20 — What didn't help.** *(finding 7)*
The ablation table.
> "We also gave the agent Entire Graph context, and memory carried between
> files. Same files, same order, same result — and up to 87% more tokens. On
> this benchmark that's overhead, so that's how we report it."

**2:20–2:50 — cfo.ai.** *(findings 8, 9)*
Ari answering over MCP; neatlogs trace for a run.
> "neatlogs records every step, and cfo.ai reads those costs live over MCP. It
> caught a 2× error in our own cost numbers. A successful migration is about 93
> cents at Sonnet prices — $2.26 if you count failed attempts — against a
> migration that costs a team days."

**2:50–3:00 — Close.**
> "Upshift: migrations that finish, with the evidence to check."

---

## 4. Posts — paste as-is, add a screenshot to each

**Post 1 — the hook** (screenshot: `upshift baseline` output)
> Pydantic's official codemod on a real 199-module repo: changes 11 files, exits
> clean. Modules that import before: 31. After: 31.
>
> Building an agent that finishes the job for #neatHack 🧵

**Post 2 — the one line** (screenshot: the `ClassVar` diff)
> The line the codemod can't write:
>
> `fetch_if_exists = False` → `fetch_if_exists: ClassVar[bool] = False`
>
> It's a class flag, not a field. Knowing that means reading the code. One file,
> +85 modules importing. #neatHack

**Post 3 — the bug the agent taught me**
> My agent kept returning the file that was breaking the build with "no changes
> needed". Four times.
>
> I'd never shown it the error. One line in the prompt fixed it. #neatHack

**Post 4 — Entire caught what I missed** (screenshot: the resolved Trail finding)
> Migration done: 199/199 modules, tests green. Pushed it to an @EntireHQ Trail.
>
> The review runner flagged it high severity: code on pydantic 2, but
> requirements.txt still pinned pydantic 1. Fresh installs would break. My
> checks couldn't see it. The agent fixes pins itself now. #neatHack

**Post 5 — cfo.ai** (screenshot: Ari's reply)
> Wired @arithecfo to my agent's telemetry over MCP so the business plan reads
> real cost per migration.
>
> First thing it did: catch a 2× error in my own unit economics. #neatHack

**Post 6 — the result** (screenshot: final numbers)
> Codemod: 31/199 modules. Upshift: 199/199 modules, 62/62 tests, and it still
> passes installed fresh from its own dependencies.
>
> Traced with @neatlogs, reviewed on @EntireHQ Trails, priced with @arithecfo.
> #neatHack

**Post 7 (optional) — the honest ablation** (screenshot: the ablation table)
> I measured whether extra context made my agent better: Entire Graph, and
> memory carried between files.
>
> Same files, same order, same result, up to 87% more tokens. On this benchmark
> it was overhead, so that's what the README says. #neatHack

---

## 5. Submission — quote the official neatlogs post on X

> **Team:** «team name»
> **Project:** Upshift — an agent that finishes migrations the official codemod can't
> **Repo:** https://github.com/romilp619/upshift
> **Demo:** «video link»
>
> Codemod: 31/199 modules. Upshift: 199/199 modules, 62/62 tests. #neatHack

Window: **Monday 12 October, 7:00–11:55 PM IST.** neatlogs and cfo.ai engage
with the first 50 quote posts — submit early in the window.

Handles confirmed from another participant's #neatHack post: `@neatlogs`,
`@EntireHQ`, `@arithecfo` (cfo.ai). Worth cc'ing on posts: `@HaimantikaM`
(Entire, judge), `@thevibefounder`, `@simranrambles`, `@bettersayAJ`.
