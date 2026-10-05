# scoped-memory

[🇧🇷 Português](README.md) | 🇺🇸 English

Agent memory with **real per-user and per-team partitioning** — plus an
automated test proving one user's memory never leaks to another, even
when both talk to **the same agent, in the same session**, and even when
they are **on the same team**.

Portfolio, fifth piece in a series on containing and controlling
autonomous agents: [guarded-agent](../guarded-agent/) (tool circuit
breaker), [browser-sandbox](../browser-sandbox/) (isolated browser),
[steerable-agent](../steerable-agent/) (runtime replanning),
[mistake-memory](../mistake-memory/) (episodic memory with enforcement).
This one is about **who can see what** in the agent's memory.

**Author:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Architecture

```
scoped-memory/
├── scoped_memory/
│   ├── store.py          # MemoryStore - SQLite, the scope filter lives in SQL
│   ├── orchestrator.py   # chat session with a switchable active user + memory extractor
│   ├── llm.py            # OpenRouter client (openai SDK, no agent framework)
│   └── display.py        # terminal rendering (rich)
├── main.py               # interactive CLI (/user, /team, /whoami, /memories)
└── tests/
    ├── test_store.py     # the leak test + team rules
    └── test_session.py   # switching users in one session doesn't mix context
```

### Where isolation lives (and where it does NOT)

One table: `memories(id, scope_type, scope_id, content, created_at)`,
with `scope_type` constrained to `user` or `team`.

Isolation **does not depend on the model**, and it is not a Python filter
applied after a global search. It is the `WHERE` clause of the **only**
method that reads the database (`MemoryStore._visible`):

```sql
WHERE (scope_type = 'user' AND scope_id = :user_id)
   OR (scope_type = 'team' AND scope_id = :team_id)
```

There is no `search_all` and no read without a `user_id`. Without a
`team_id`, only the first half runs. Empty ids are rejected. Relevance
ranking runs **on the already-filtered result**, never before.

### Team memory is explicit

`add(content, user_id, team_id=None)` always writes the personal row; a
**second** `scope_type=team` row is written only when `team_id` is
passed. Nothing is auto-promoted from personal to team.

In chat, a separate LLM call (the extractor) proposes the scope after
each reply, but the `Orchestrator` only accepts `scope=team` if the user
**has an active team** **and** explicitly said it's for the team
(`time`, `equipe`, `team` — a deterministic regex, outside the model).

### Why chat history is partitioned too

Partitioning persisted memory isn't enough. With a single message list
per session, Alice's secret would be in the history sent to the model
when Bob asks his next question — the leak wouldn't even touch the
database. So history (and the active team) is kept **per `user_id`**.

## Setup

```bash
cd scoped-memory
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your OPENROUTER_API_KEY
python main.py --db demo.db
```

Default model: `qwen/qwen3.8-27b:free` on [OpenRouter](https://openrouter.ai).
Free models rate-limit (429) often and sometimes return empty content;
the client falls back through `OPENROUTER_FALLBACK_MODELS` in order.

## Demo script

See the [Portuguese README](README.md#roteiro-da-demo-gravável) for the
exact terminal script (prompts are in Portuguese):

1. `/user alice` → tells the agent a specific secret
2. `/user bob` → asks about Alice's secret → the agent doesn't know
3. `/team eng` for both → something said "for the team" shows up for both
4. `pytest -v` live, showing the leak tests passing

## Limitations (it's an MVP)

- Word-overlap ranking, not embeddings — the project is about isolation.
- Identity is whatever `/user` says; in production `user_id` comes from a
  verified token, never from user text.
- Team membership isn't validated; in production `team_id` would only be
  accepted for actual members.
