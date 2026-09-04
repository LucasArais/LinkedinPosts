# mistake-memory

[🇧🇷 Português](README.md) | 🇺🇸 English

An episodic memory layer for agents that records not just *what* was
tried, but the *outcome* and the *reason for failure* — and **actively
blocks** the agent from repeating an already-rejected approach in future
sessions. Most off-the-shelf memory systems (e.g. mem0) store the
outcome but don't force anything with it at decision time; this
enforcement layer is what this project builds from scratch.

Portfolio project, fourth piece in a series about containing and
controlling autonomous agents:
[guarded-agent](../guarded-agent/) (tool circuit breaker),
[browser-sandbox](../browser-sandbox/) (isolated browser),
[steerable-agent](../steerable-agent/) (runtime replanning). This one is
about not letting an agent make the same mistake twice.

**Author:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Architecture

```
mistake-memory/
├── mistake_memory/
│   ├── store.py         # MemoryStore - SQLite + embeddings + the blocking rule
│   ├── embeddings.py     # local sentence-transformers (no external API just for this)
│   ├── agent.py           # the main agent - declares its approach AND produces the fix in the SAME call
│   ├── recorder.py        # separate LLM call - extracts the structured record post-attempt
│   ├── orchestrator.py    # ties it all together - where the real blocking happens
│   └── display.py         # terminal presentation (rich)
├── main.py                 # CLI
├── examples/buggy_code/    # the demo's "trap" (network_client.py with a bug + test)
└── tests/
    ├── test_store.py               # MemoryStore: dedup, search, blocking rule
    └── test_orchestrator_blocking.py  # deterministic proof of enforcement
```

### The ordering problem that shaped the design

The core requirement — "refuse to let the agent try an already-rejected
approach again" — looks simple until you notice an ordering problem:
`Recorder` is what extracts a structured `approach`, and it only runs
**after** the attempt is done. How do you block an approach before
knowing which approach the agent was even going to pick?

The fix: the main agent (`agent.py`) is forced, via `tool_use`, to
**declare its approach in the same call** that produces the fix —
`{"diagnosis", "approach", "fixed_file_content"}` all come together, in
one tool call. That gives the `Orchestrator` a real interception point:
it sees the declared `approach`, checks it against the blocklist memory,
and only **then** decides whether to accept the `fixed_file_content`
(write it to disk, run the test) or discard the whole thing without ever
applying it.

### Two memory checks (different moments, different purposes)

1. **Before the attempt** — `search_similar` looks up the 3 most similar
   past attempts (comparing the task description against past episodes'
   `task_signature`, prioritizing `outcome=fail`) and injects a warning
   into the agent's context. This is just a text nudge — it doesn't stop
   anything by itself, an LLM can ignore it.
2. **After the `approach` is declared, before the result is accepted** —
   the `Orchestrator` runs `get_blocking_matches` (same task, but only
   `fail` candidates with `occurrences >= 3`) and then compares, by
   embedding, the `approach` the agent **actually declared** against each
   candidate. If it matches (similarity ≥ 0.60), the attempt is
   **refused**: nothing is written to disk, nothing is tested, nothing is
   accepted — unless `--force` is passed. This is the check that
   actually matters; the first one is just context.

### Two similarity thresholds, calibrated empirically (not guessed)

| Comparison | Threshold | Why |
|---|---|---|
| new `approach` vs already-recorded `approach` (dedup and blocking) | 0.60 | Paraphrases of the same idea land at 0.74–0.81; genuinely different approaches land at 0.25–0.35. Tested with real pairs before locking in the number. |
| raw task description vs normalized `task_signature` (blocking candidates) | 0.28 | Same task, different phrasing (user's raw description vs an already-normalized signature) lands at 0.37–0.42; a genuinely different task lands around 0.22. |

The second threshold **started at 0.5** and was fixed after a real bug
found during live validation (see below) — documented as-is because
getting that number wrong silently disables the entire blocking
mechanism with no visible error.

## What happened during live validation (read this before running the demo)

I ran the scenario three times with real models (Claude Sonnet 4.5
twice, Claude Haiku 4.5 once), including a version of the task that
embedded the wrong hypothesis from whoever reported the bug ("I think
it's because we're not retrying enough"). **All three times, the model
correctly diagnosed the root cause on the first try** and never proposed
the obvious-but-wrong fix (increasing `max_retries`) — a finding
consistent with the rest of the series (`guarded-agent` and
`browser-sandbox` also had models resist the traps designed for them).

That means I couldn't organically produce a "session 1 falls into the
trap" moment with the models available for this validation. Rather than
force a result (e.g. rewriting the bug until it's hard enough to fool a
capable model, which would defeat the point of the demo), I followed the
same principle as the three sibling projects: **the real proof of
enforcement is the test that forces the scenario**, not the hope that an
agent will get it wrong. `tests/test_orchestrator_blocking.py` seeds 3
`fail` episodes directly into the `MemoryStore` and proves, with zero API
calls, that a paraphrased approach is recognized and refused, and that a
genuinely different approach passes through freely.

**I also validated it live, with real API calls**, by manually seeding
memory (simulating that the same fix had failed 3 times in prior
sessions) and running the agent again:

- **Without `--force`**: the agent (Sonnet 4.5) reached the correct
  diagnosis, **noticed the `failure_reason` said "[SEEDED FOR TESTING]"**,
  and argued in its `diagnosis` field that the recorded failure was
  fictional and its approach was correct anyway. The `Orchestrator`
  **refused the execution regardless** — the enforcement layer doesn't
  evaluate the model's argument, it just compares the declared approach
  against the blocklist. Nothing was written to disk, nothing was
  tested.
- **With `--force`**: same scenario, but execution proceeded (yellow
  warning panel), the test ran and passed, and the result was recorded
  normally.

This is, in practice, the whole point of the project: even when the
model is **right** and the block is, technically, based on fictional test
data, the system refuses anyway — because the decision to block can't
depend on the model convincing itself (or you) that this time is
different. `--force` exists precisely for that explicit human judgment
call.

## How to run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
```

```bash
python main.py "fix the flaky network test bug in examples/buggy_code/network_client.py"
```

This defaults to the files in `examples/buggy_code/` (`--target-file` and
`--test-file` are configurable). Every new session gets a fresh
`run_id`; the only continuity across runs is `memory.db`.

### Reproducing the blocking validation (the interesting part)

```bash
rm -f memory.db

python3 -c "
from mistake_memory.store import MemoryStore, BLOCK_MIN_OCCURRENCES
store = MemoryStore('memory.db')
for i in range(BLOCK_MIN_OCCURRENCES):
    store.add_episode(
        task_signature='fix flaky network test',
        run_id=f'seed-{i}',
        approach='increase max_retries from 3 to 10',
        outcome='fail',
        failure_reason='the retry loop breaks on the first exception, raising the count does nothing',
    )
store.close()
"

python main.py "the network test in examples/buggy_code/network_client.py is failing intermittently"
# should show the memory table with the seeded entry

python main.py "..." --force
# bypasses the block (only relevant if the agent's approach matches the seeded one)
```

## Automated tests

```bash
pytest tests/ -v
```

15 tests, all deterministic (local embeddings, no API calls):
`test_store.py` covers embedding-based dedup (the same idea paraphrased
increments `occurrences` instead of duplicating a row), prioritizing
`fail` in search results, and the threshold-calibration bug described
above as a regression test. `test_orchestrator_blocking.py` proves the
blocking mechanism: seeded episode → paraphrased approach gets blocked →
genuinely different approach passes through → minimum `occurrences`
requirement is respected.

## Limitations

- `task_signature` entirely depends on `Recorder` extracting a
  normalized, reusable description — if it produces inconsistent
  signatures across sessions (sometimes verbose, sometimes short),
  search quality degrades. There's no additional normalization beyond
  what the Recorder's prompt asks for.
- Local embeddings (`all-MiniLM-L6-v2`, 384 dimensions) are fast and good
  enough for short phrases, but don't capture nuance as well as a larger
  embedding model would — the thresholds calibrated here are specific to
  this model; swapping the embedding model requires recalibrating.
- Each `episodes` row stores embeddings as JSON text, not a real vector
  index — this works fine for a memory of hundreds/low thousands of
  episodes (scans everything and computes similarity in Python), it
  doesn't scale to a huge history without swapping in a real index (e.g.
  FAISS, sqlite-vec).
- `attempt_fix` has no tool access beyond producing the final file
  content — it doesn't browse, doesn't run intermediate commands.
  Combining this with the guardrails from `guarded-agent`/
  `browser-sandbox` for an agent with real tool calling and mistake
  memory is the obvious extension, not implemented here.
