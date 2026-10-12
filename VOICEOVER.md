# Voiceover — read aloud, ~3:35

Numbers are spelled the way you should say them. Pause at every blank line.
Target pace is about 150 words a minute; if you are running long, the line to
drop is clip 7.

---

### Clip 1 — `upshift baseline` · 0:00–0:25

Pydantic version two broke every version one codebase.

The official fix is a codemod. Here it is on a real repository — a hundred and
ninety-nine modules. It changes eleven files and exits clean.

Modules that actually import, before: thirty-one. After: thirty-one.

Nothing moved. That is the problem Upshift solves.

---

### Clip 2 — the error, then the two fixes · 0:25–0:50

Here is the error pydantic two gives you.

A non-annotated attribute was detected: fetch if exists equals False. Pydantic
needs to know whether that is a field, or just a constant on the class.

The answer is different on every line, and the only way to tell is to read the
code.

Here, the agent decided it is a field. Colon, bool.

And here, in another file, it decided the opposite. Colon, ClassVar of string.

Same error. Opposite fixes. A codemod cannot make that call — and that first
file alone takes the repository from thirty-one modules importing to a hundred
and sixteen.

### Clip 3 — the run, sped up · 0:50–1:22

So we built an agent that reads, edits, and checks.

Every edit is verified against the whole package and the full regression suite.
If the numbers do not improve, the edit is rolled back and it tries again with
the new error.

Watch line nine. The agent was handed one file, worked out the real cause was
in a different one, and said so — and the next step goes straight there.

And here is where it lands. A hundred and ninety-nine of a hundred and
ninety-nine modules. Sixty-two of sixty-two tests. Complete.

> *Optional four-second cutaway, over* `evidence/logs/deepseek/run-no-entire.log`
> *line 6 —* `att=2 rb=1`*:*
> "Here is a rollback in an earlier run: rejected once, kept the second time,
> thirty more modules."

---

### Clip 4a — the failing trace · 1:20–1:50

While we were building this, our own agent had an incident. neatlogs is where
we found it.

A run finished. It printed done. A hundred and ninety-nine of a hundred and
ninety-nine modules importing. Six tests were still failing.

Look at the end of the trace. Four steps in a row, each one a model call, each
one with nothing underneath it. No edit. No verification. Nothing.

---

### Clip 4b — Ask neat AI · 1:50–2:05

So we asked neatlogs about it.

Four different files all reported the same root cause — and our harness
followed that redirect while fixing imports, then silently dropped it while
fixing tests.

---

### Clip 4c — `scripts/incident.py` · 2:05–2:20

Here are both runs side by side.

Seven wasted redirects before the fix. One after. Twenty-nine steps down to
twenty-three. Fifty-six of sixty-two tests, up to sixty-two of sixty-two.

And the agent will no longer print "complete" while a single test is failing.

---

### Clip 5 — Entire Trail · 2:20–2:45

The migrated branch goes to an Entire Trail.

Its review runner caught something our own checks could not: the code was on
Pydantic two, but requirements dot txt still pinned Pydantic one. Anyone
installing it would have got a broken package.

The agent fixes its own pins now. And installed fresh, from its own declared
dependencies, the result is still one ninety-nine and sixty-two.

---

### Clip 6 — cfo.ai · 2:45–3:10

cfo dot ai reads those same run costs live, over MCP. Not a spreadsheet — the
agent's own telemetry.

The first thing it did was catch a two-times error in our own unit economics.

A successful migration costs about ninety-three cents at Sonnet prices. Two
dollars twenty-six if you pay for the failed attempts too. Against a migration
that costs a team days.

---

### Clip 7 — the ablation · 3:10–3:25 *(drop this first if long)*

We also measured whether extra context helped. Entire Graph, and memory carried
between files.

Same files. Same order. Same result — and up to eighty-seven percent more
tokens. On this benchmark it was overhead, so that is what our README says.

---

### Clip 8 — the repo · 3:25–3:35

Upshift. Migrations that finish, with the evidence to check.

---

## Recording the audio

- One pass over the finished timeline, not line by line.
- Read the numbers slowly. They are the whole argument.
- If you fumble, pause two seconds and redo the sentence — easy to cut.
- Clips 4a to 4c are the segment the organisers asked for. Do not rush them.
