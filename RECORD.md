# Recording the demo video — step by step

One video, ~3:30. Covers every hackathon requirement. Work top to bottom.

Deadline: **Monday 12 Oct, 7:00–11:55 PM IST.** Submit early in the window —
neatlogs and cfo.ai engage with the first 50 quote posts.

---

## Step 0 — Start the long capture first (do this before anything else)

A full run takes about 7½ minutes. You cannot film it live inside a 3½-minute
video, so capture it now and let it finish while you set everything else up.

Start your screen recorder on a terminal, then:

```bash
cd /home/romil/neathack && UPSHIFT_RUNS_DIR=/tmp/upshift-demo-runs .venv/bin/python -m upshift run --target python-client --config no-entire --run-id demo --workdir /tmp/upshift-demo 2>&1 | tee /tmp/demo-run.log
```

`--workdir` runs in a private git worktree, so `upshift/verified` and every
existing branch are untouched. `UPSHIFT_RUNS_DIR` sends the new run record to a
throwaway directory, so `evidence/runs/` stays frozen at 14 runs and every
number published in the README, BUSINESS.md and SUBMISSION.md stays true.

Stop the recorder when it prints `COMPLETE`. You will speed this clip up 8–10×
in the edit and use about 35 seconds of it. **Keep recording even if it fails** —
a rollback on screen is worth filming.

While it runs, do steps 1 and 2.

---

## Step 1 — Prepare the screen

- Terminal font to **18–20pt**, window roughly 110×30, dark theme, `clear` first.
- Hide notifications, bookmarks bar, and anything personal.
- **Close the `.env` file and never show it.** It has live keys in it.
- Test your mic: record 10 seconds, play it back. Bad audio sinks good demos.

Open these six browser tabs, in this order, and leave them on the right view:

| # | Tab | Left on |
|---|---|---|
| 1 | neatlogs → **traces** | the **01:56 PM Oct 11** trace — output reads `Passed: 56 Failed: 2 Errors: 2` |
| 2 | neatlogs → **traces** | the **02:54 PM Oct 11** trace — output reads `Passed: 62 Failed: 0 Errors: 0` |
| 3 | entire.io | https://entire.io/gh/romilp619/python-client/trails/1 — the resolved high-severity finding |
| 4 | cfo.ai | the chat with Ari, plus the "Migration runway" model |
| 5 | cfo.ai → MCP | DEMOMCP showing **Connected**, 5 tools |
| 6 | GitHub | https://github.com/romilp619/upshift |

Terminal tabs to have ready (run each once now so there is no cold-start pause):

```bash
cd /home/romil/neathack && .venv/bin/python -m upshift report
```

---

## Step 2 — The neatlogs incident, in your own words

This is the segment the organisers added on 11 Oct and the one most likely to be
scored directly. **Do not say neatlogs raised an incident — your Incidents list
is empty because no Issue snapshot has been published yet.** Say you pointed
neatlogs' investigation at the trace. Everything below is true either way.

In tab 1, scroll to the end of the run. You are looking for this sequence of
`migrate:` traces:

```
22  migrated  m=199 t=47  invocable/config.py
23  redirect  m=0  t=0    base/model.py                        -> invocable/config.py
24  redirect  m=0  t=0    block_and_tag_plugin_output.py       -> plugin_output.py
25  redirect  m=0  t=0    raw_data_plugin_output.py            -> plugin_output.py
26  migrated  m=199 t=49  plugin/capabilities.py
27  redirect  m=0  t=0    training_parameter_plugin_output.py  -> plugin_output.py
28  redirect  m=0  t=0    train_plugin_output.py               -> plugin_output.py
29  migrated  m=199 t=56  plugin_output.py            <- reached on the last step
```

Four different files, all naming the same root cause, four times. Every
`m=0 t=0` row is a full model call that produced no edit.

Press **Investigate further** or **Ask AI about this** on that trace and film
whatever it returns — that is a live neatlogs artifact and it belongs in the cut.

Then switch to tab 2 (the run after the fix): **1 redirect, followed, 23 steps,
62/62.**

Have `evidence/runs/PROVENANCE.md` open in a window behind, in case you want to
cut to it.

---

## Step 3 — Shot list

Record each shot separately. Do not try to do it in one take.

### Shot 1 — the problem · 0:00–0:25
Screen: terminal.
```bash
cd /home/romil/neathack && .venv/bin/python -m upshift baseline --target python-client
```
> "Pydantic v2 broke every v1 codebase. The official fix is a codemod. On this
> real repo — 199 modules — it changes 11 files, and the number of modules that
> actually import goes from 31 to 31."

*Safe to run on camera:* `baseline` rewinds the working branch
`upshift/pydantic-v2` to the pinned commit. It has been tagged
`demo-backup/pydantic-v2` so nothing is lost, and `upshift/verified` (caab59f)
and `upshift/verified-run-1454` are different branches and are not touched. If
you would rather not risk it live, the saved output is in
`bench/baseline-python-client.md` and reads the same on screen.

### Shot 2 — why a codemod can't · 0:25–0:45
Screen: the `fetch_if_exists = False` error, then the agent's diff adding
`ClassVar[bool]`.
> "A codemod renames things. It can't tell that this is a class flag, not a
> field. That takes reading the code. One line — and eighty-five more modules
> import."

### Shot 3 — the agent running · 0:45–1:20
Screen: your Step 0 clip, sped up 8–10×. Pause on a `->` line and on `COMPLETE`.
> "Every edit is checked against the whole package and the full test suite. If
> the numbers don't improve, the edit is rolled back and it tries again with the
> new error. Here it worked out the real cause was in a different file and went
> there instead. End state: 199 of 199 modules, 62 of 62 tests."

### Shot 4 — neatlogs · 1:20–2:20 ← the longest shot, give it the time

Three screens in this order.

**a. The trace.** Tab 1, the **01:56 PM Oct 11** trace. Press **EXPAND ALL** and
scroll to the bottom of the step tree. Four `migrate:…_plugin_output.py` AGENT
spans sit in a row, each with **no children and almost no duration** — on a
redirect the agent stops before verifying, so nothing runs. Then
`migrate:…/plugin_output.py`, with real work under it, as the very last step.
Let the OUTPUT panel show `Passed: 56 Failed: 2 Errors: 2`.

The model's reply text is *not* in the trace — the Anthropic client was never
instrumented. Do not go looking for `NO_CHANGE_NEEDED` on screen. The shape is
the evidence.

**b. Ask neat AI.** Top right of the trace. Paste:

> This run finished but six tests still failed. Four steps in a row produced no
> edit and pointed at the same file. What went wrong?

Film whatever it returns. This is the neatlogs investigation artifact.

**c. The numbers.** Terminal:

```bash
cd /home/romil/neathack && .venv/bin/python scripts/incident.py
```

Both runs side by side, straight out of the recorded evidence. Then tab 2 —
`Passed: 62 Failed: 0 Errors: 0`.

### Shot 5 — Entire · 2:15–2:40
Screen: tab 3, the resolved finding.
> "The branch goes to an Entire Trail, and its review runner caught something our
> own checks couldn't: the code was migrated, but requirements.txt still pinned
> pydantic 1. Anyone installing it would have got a broken package. The agent
> fixes pins itself now — and installed fresh from its own declared
> dependencies, the result is still 199 and 62."

### Shot 6 — cfo.ai · 2:40–3:05
Screen: tab 5 (Connected, 5 tools) for two seconds, then tab 4 (Ari + the runway
model).
> "cfo.ai reads those same run costs live over MCP — not a spreadsheet, the
> agent's own telemetry. The first thing it did was catch a 2× error in our unit
> economics. A successful migration is about 93 cents at Sonnet prices, $2.26 if
> you pay for the failed attempts too, against a migration that costs a team
> days."

### Shot 7 — what didn't help · 3:05–3:20 *(cut this first if you run long)*
Screen: terminal, `upshift report`, or the README ablation table.
> "We also measured whether extra context helped: Entire Graph, and memory
> carried between files. Same files, same order, same result — and up to 87%
> more tokens. On this benchmark it was overhead, so that's what our README
> says."

### Shot 8 — close · 3:20–3:30
Screen: tab 6, the repo.
> "Upshift: migrations that finish, with the evidence to check."

---

## Step 4 — Before you export

- Watch it once with the sound off. Can a judge follow it from the screen alone?
- Watch it once with the screen off. Does the audio still make the argument?
- Check no frame shows `.env`, an API key, a token, or your AWS console.
- Burn in the numbers as on-screen text at the moments you say them:
  **31/199 → 199/199** and **0 → 62/62**.

---

## Step 5 — Requirements map

Check every row before you submit.

| Requirement | Covered by | Status |
|---|---|---|
| The problem the agent solves | shots 1–2 | |
| The agent works, end to end | shot 3 | |
| **neatlogs** — identifying and resolving an incident the agent ran into | shot 4 | |
| **Entire** — Checkpoints / Graph / Trails | shot 5 (Trail), shot 7 (Graph ablation) | |
| **cfo.ai** — cost, pricing, runway | shot 6 | |
| The agent improved — before and after, with numbers | shot 4 (56/62 → 62/62, 7 redirects → 1) | |
| The agent recovers from failures | shot 3 (rollback), shot 5 (Trail finding) | |
| Public repo, dated commits | shot 8 | |
| Built in public, #neatHack | posts — `SUBMISSION.md` §4 | |
| Submission quote-post | `SUBMISSION.md` §5 — **team name still blank** | |

---

## Step 6 — After the video is recorded

In this order, from `SUBMISSION.md` §1b:

1. Post the video + the seven posts in §4, tagging `@neatlogs`, `@EntireHQ`,
   `@arithecfo`.
2. You: revoke the GitHub PAT, rotate the Token Harbor and neatlogs keys.
3. Claude: rotate the MCP key, `entire enable`, attach this session as a
   checkpoint, push.
4. Terminate EC2 `i-06196a09ecfbe54b1` (see `DEPLOY.md`).
