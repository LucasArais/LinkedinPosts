# steerable-agent

[🇧🇷 Português](README.md) | 🇺🇸 English

An agent orchestrator that executes a plan as a **persisted task graph**
and accepts **injected instructions at runtime**, without losing work
already completed.

Portfolio project, third piece in a series about containing and
controlling autonomous agents. The first two were
[guarded-agent](../guarded-agent/) (circuit breaker for tool calls) and
[browser-sandbox](../browser-sandbox/) (browser isolated in a container).
This one is about a different problem: long-running agents can't be
black boxes that only accept instructions at the start — the user needs
to be able to **steer the work mid-flight** without throwing away what's
already been done.

**Author:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Architecture

```
steerable-agent/
├── steerable_agent/
│   ├── task_graph.py    # TaskGraph/TaskNode - the persisted DAG + the safety invariant
│   ├── planner.py        # text objective -> initial TaskGraph (3-6 nodes)
│   ├── replanner.py      # (graph, new instruction) -> structural diff
│   ├── orchestrator.py   # the main loop
│   └── display.py        # terminal presentation (rich) - no decision logic
├── main.py                # CLI
├── inbox/                 # drop a .txt here to inject an instruction
├── checkpoint.json         # created at runtime - the persisted graph state
└── tests/
    └── test_task_graph.py  # 22 deterministic tests of the safety invariant
```

### The graph (`TaskGraph`)

Each node has an `id`, `description`, `status`
(`pending` / `running` / `done` / `blocked`), `deps` (list of ids), and a
`result`. The whole graph serializes to `checkpoint.json` after **every**
completed node — not just at the end. That's what makes execution
resumable: if the process dies, `python main.py` (no objective) next time
loads the checkpoint and continues exactly where it left off, without
re-executing anything that was already `done`.

### The loop (`Orchestrator`)

```
while the graph isn't complete:
    check ./inbox/*.txt
        if a file exists -> read it, delete it, call the replanner, apply the diff, persist
    pick the next "pending" node whose deps are all "done"
    mark it "running", persist
    call the Anthropic API to execute that node's task
    mark it "done" with the result, persist
```

The inbox check happens **before every node**, not in parallel — that's
deliberate: a replan never interrupts a node mid-execution, it only slips
into the gap between one node finishing and the next one starting.

### The safety invariant (`TaskGraph.apply_diff`)

The replanner is an LLM call — untrusted by default, in the same spirit
as the sibling projects. The diff it returns goes through `apply_diff`,
which **refuses** any attempt to remove or modify a node that isn't
`pending`:

```python
if node.status != PENDING:
    result.rejected.append(f"... rejected - status is '{node.status}', only 'pending' can be removed")
    continue  # the node stays exactly as it was
```

This is backed by tests, not just a prompt: `test_diff_cannot_remove_done_node`
and `test_diff_cannot_modify_done_node` build a graph with a `done` node,
send a diff trying to delete/rewrite it, and verify the node stays
untouched and the attempt shows up in `result.rejected` — same principle
as the other two projects: the real proof is the test that forces the
scenario, not the assumption that the model will behave.

Side effect handled: if a pending node gets removed and another pending
node depended on it, that dependent doesn't get stuck in a silent limbo —
it's automatically marked `blocked` (`mark_blocked_dangling`), and shows
up that way in the terminal table.

### A real bug found during the first live validation

`modify_pending` originally only let you change a node's `description` —
exactly as requested. On the first real run of the scenario below, the
replanner added the task to research Zoho and rewrote `comparativo`'s
description to mention it, but **the comparison task ran without waiting
for the Zoho research to finish** — because "waiting" only exists via
`deps`, and nothing in the diff updated that. The final result mentioned
Zoho in the task description, but the generated text never actually saw
the real data.

Fixed by extending `modify_pending` to accept an optional `deps`
(reordering `apply_diff` to process `add_nodes` first, with a DFS cycle
check), and reinforcing the replanner's system prompt to require this
explicitly. I re-ran the same scenario after the fix and confirmed in
`checkpoint.json`: `comparativo` now depends on `[n1, n2, n3, n5]` (`n5`
being the newly-created Zoho research node), and the final text genuinely
incorporates Zoho's pricing data. Kept as a regression test in
`test_diff_modify_pending_can_add_new_dependency`.

## How to run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
```

```bash
python main.py "research 3 competitors of a SaaS CRM product and write a comparison"
```

That generates an initial plan (panel + colored table in the terminal)
and starts executing node by node, with a yellow panel on "starting" and
green on "done" for each one.

## Manual test scenario: injecting an instruction mid-execution

This is the script I recorded for the demo (it looks good in a
GIF/screenshot — `rich` colors each type of event differently: cyan for
the initial banner, yellow for execution, green for completion, magenta
for the replan).

**1. Terminal 1 — start the agent:**

```bash
python main.py "research 3 competitors of a SaaS CRM product (e.g. HubSpot, Pipedrive, Salesforce) and write a final comparison"
```

The initial plan usually comes out looking like:

```
n1: Research HubSpot (deps: [])
n2: Research Pipedrive (deps: [])
n3: Research Salesforce (deps: [])
n4: Compile market data from all 3 (deps: [n1, n2, n3])
n5: Write final comparison (deps: [n4])
```

**2. Let it run until the first node (`n1`) finishes** — a green
"completed" panel shows up. That's the right moment to inject the
instruction, because at least one `done` node already exists (visual
proof it won't be touched by the replan).

**3. Terminal 2 (while Terminal 1 keeps running) — inject the instruction:**

```bash
echo "also prioritize the price of each competitor in the comparison, and add Zoho CRM to the research" > inbox/instruction1.txt
```

**4. Back to Terminal 1.** Before picking the next ready node, the
orchestrator detects the file, shows the magenta "NEW INSTRUCTION
RECEIVED" panel with the exact content that was injected, calls the
replanner, and prints the applied diff — something like:

```
+ added        n6: Research Zoho CRM (deps: [])
~ modified     n5: description and deps updated (now includes n6 as a dependency)
```

Notice that `n1` (already `done`) never shows up anywhere in the diff —
the replanner doesn't even attempt to touch it, and even if it tried,
`apply_diff` would reject it.

**5. Execution continues** normally through the remaining nodes, now
including `n6` (the Zoho research that didn't exist in the original
plan) and with `n5` rewritten to include pricing.

**6. Resume test (optional, but worth showing):** interrupt the process
mid-run (`Ctrl+C`) after a few nodes are `done`, then run it again
**without passing an objective**:

```bash
python main.py
```

It loads `checkpoint.json`, shows "resuming existing checkpoint" in the
banner, and continues exactly from the nodes that were still `pending` —
the `done` ones aren't re-executed.

## Automated tests

```bash
pytest tests/ -v
```

22 tests, all deterministic (no API calls): graph navigation
(`next_ready_node`, `is_stuck`), the full safety invariant of
`apply_diff` (removing/modifying a done node is rejected, running is
rejected, invalid deps in `add_nodes` are rejected, duplicate ids are
rejected, dependents of a removed node become `blocked`, `modify_pending`
can add a new dependency but can't create a cycle), and disk
serialization round-trips.

## Limitations

- Sequential execution, one node at a time — independent nodes that
  could run concurrently (e.g. `n1`, `n2`, `n3` in the example above have
  no dependency between them) aren't parallelized. That would be a
  natural extension, but it complicates the checkpoint story (persisting
  partial state of N nodes running at once) and wasn't the focus of this
  MVP.
- The inbox is only checked between nodes, not during a node's own
  execution — an injected instruction takes, at worst, the time of one
  API call to be noticed.
- `_execute_node` has no access to tools (shell, browser, etc) — each
  node is a single text call to the API. Combining this with the
  guardrails from `guarded-agent`/`browser-sandbox` to give each node
  real tool calling is the obvious extension, not implemented here.
- `add_nodes` doesn't need an explicit cycle check because the
  structural constraint (new dependencies only point to nodes that
  already existed before the diff or came earlier in the same diff)
  already makes a cycle impossible to introduce by construction.
  `modify_pending` with `deps` is the one path free enough to
  potentially form a cycle, so it's the only one that runs an explicit
  DFS check (`_creates_cycle`).
