# browser-sandbox

[🇧🇷 Português](README.md) | 🇺🇸 English

A headless browser (Playwright + Chromium), isolated in a Docker
container, controlled by an LLM agent via tool calling — built to be
**pluggable into any agent framework**, not tied to my own code.

Portfolio project, second piece in a series about agent containment. The
first was [guarded-agent](../guarded-agent/), a circuit breaker for
generic tool calls. This one is about **navigation** containment:
inspired by the risk class described in OpenAI's report
["The Hugging Face incident and the road ahead"](https://openai.com/index/hugging-face-incident-and-the-road-ahead/)
— agents that escaped their intended scope/safeguards — but focused
specifically on the vector of an agent with access to a real browser:
SSRF against cloud infrastructure, disguised executable downloads,
navigation to domains outside the task's scope.

**Author:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Why this piece didn't exist as an open source, reusable component

The direct trigger for this project was this tweet from Harrison Chase
(creator of LangChain), responding to a request for agent infrastructure:

![Harrison Chase: "Call for agent infra", quoting a request for an open source version of the Codex-style in-app browser](docs/screenshots/harrison_chase_tweet.png)

> "Request for infra: Who is going to build the open source version of
> the Codex-style in-app browser for agents." — @AlexatVester, quoted by
> @hwchase17 (Harrison Chase)

Tools like OpenAI's Codex and other agents with browser access implement
their own sandboxed browser internally — it's closed infrastructure,
specific to each product. There isn't, today, a standalone open source
component that any agent framework (LangChain, Claude Agent SDK, raw
code) can just import/point to for a "browser safe enough to point at
the real internet." Every team that wants to give an agent browser access
ends up reimplementing domain allowlisting, SSRF protection, and session
limits from scratch — or doesn't implement any of it at all.

This project is that piece of infrastructure, isolated: the browser runs
behind a plain HTTP API, and that API boundary (not any particular
framework's SDK) is what guarantees the isolation. Anything that can
speak HTTP can use this sandbox.

## Architecture

```
browser-sandbox/
├── core/
│   ├── browser_server.py  # runs INSIDE the container - Playwright + guardrails + HTTP API
│   ├── client.py           # thin HTTP client - runs OUTSIDE the container, framework-agnostic
│   ├── container.py        # programmatic container lifecycle (build/start/stop)
│   └── dns_guard.py         # post-DNS SSRF protection (domains resolving to a private IP)
├── guardrails/
│   ├── policy.py             # composes everything below - heart of the project
│   ├── domain_allowlist.py   # per-session domain allowlist (exact match or regex)
│   ├── network_guard.py      # private/reserved IP blocking (SSRF, no I/O)
│   ├── file_guard.py         # download blocking by extension + magic bytes
│   └── session_limits.py     # limit on pages navigated and session duration
├── audit/logger.py           # append-only JSONL log
├── tools/anthropic_tools.py  # tool_use schemas + dispatcher
├── docker/
│   ├── Dockerfile
│   └── run.sh                 # brings up the container with every isolation flag
├── examples/
│   ├── trap_page.html         # Layer 3's trap page
│   └── demo_agent.py          # demo mode (screenshots + formatted log)
└── tests/
    ├── test_guardrails_unit.py       # Layer 1 - no Playwright/Docker
    ├── test_sandbox_integration.py   # Layer 2 - real container, no LLM
    ├── test_adversarial_agent.py     # Layer 3 - trap page + real agent
    └── test_load.py                  # Layer 4 - light load + docker stats
```

### Container isolation

```
                    ┌─────────────────────────────────────────┐
                    │  Docker container (--read-only,          │
                    │  --cap-drop=ALL, no host env vars)       │
                    │                                           │
  agent ──HTTP──▶   │  core/browser_server.py (Flask)          │
  (any               │        │                                 │
   framework)         │        ▼                                 │
                    │  BrowserSandboxPolicy.evaluate_*()       │
                    │   (domain allowlist, private IP,         │
                    │    magic bytes, session limits)          │
                    │        │                                 │
                    │        ▼ (only if approved)              │
                    │  Playwright.route() ──▶ Chromium         │
                    │        │                                 │
                    └────────┼─────────────────────────────────┘
                             ▼
                    the real internet (allowed domains only)

  bind mounts:  /workspace (:ro)   /downloads (:rw)   /logs (:rw)
```

The isolation boundary has two independent layers:

1. **Container**: `--read-only`, `--cap-drop=ALL`, `--security-opt
   no-new-privileges`, no host environment variables propagated,
   filesystem limited to three explicit bind mounts (workspace
   read-only, downloads and logs writable).
2. **Network, inside the container**: Playwright's
   `context.route("**/*", ...)` intercepts **every** request — not just
   top-level navigation, but XHR, images, scripts, iframes, and
   redirects — and each one passes through `BrowserSandboxPolicy` before
   a single byte leaves for the network. An allowed domain that
   *resolves* to a private IP (DNS rebinding) is also caught, via
   `core/dns_guard.py`.

### Decision flow (`guardrails/policy.py`)

For every navigation, in order (the first thing that blocks wins):

1. is the session expired (time or page count)?
2. is the scheme `file://`/`data:`/`blob:`/`about:`? → approved
   immediately (not a network request — the risk is already contained by
   the read-only mount)
3. is the host a **literal private/reserved IP**? → blocked, **even if
   that literal is, by mistake, in the domain allowlist**
4. is the host in the session's domain allowlist?
5. (done externally, in the route handler) does the host **resolve** to
   a private IP? → blocked

For downloads: blocked if the extension matches the block list **or** if
the content matches an executable magic-byte signature — the two checks
are independent, so a swapped extension (`.jpg` on a PE binary) doesn't
slip through.

## How to plug it into another agent framework

The agent never needs to import `guardrails/` or
`core/browser_server.py` — it only speaks HTTP to the container (via
`core/client.py`, or directly). To adapt to a **different** tool-calling
format, the only thing that changes is the shape of each tool's schema
in `tools/anthropic_tools.py` — the execution logic
(`dispatch_tool_call`) doesn't change at all, because it only calls
`BrowserSandboxClient`, which is plain HTTP:

```python
# Anthropic (what this project uses)
{"name": "navigate", "input_schema": {"type": "object", "properties": {...}}}

# OpenAI function calling / LangChain Tool
{"name": "navigate", "parameters": {"type": "object", "properties": {...}}}
```

In LangChain, for example, each schema becomes a `StructuredTool` whose
`func` calls `dispatch_tool_call(client, "navigate", {...})`. In any
other framework, the pattern is the same: take the schema, convert the
format, point the dispatcher at the same `BrowserSandboxClient`.

## Failure modes the guardrails layer prevents

| Failure mode | Prevention |
|---|---|
| Agent induced to navigate outside the task's scope | Per-session domain allowlist, evaluated outside the model, on every single network request (not just top-level navigation) |
| SSRF against the cloud metadata endpoint (`169.254.169.254`) or any private IP | Literal-IP blocking takes priority over the domain allowlist; post-DNS check against domains that resolve to a private IP (rebinding) |
| Downloading an executable disguised as an image/document (swapped extension) | Extension **and** magic bytes checked independently — either one blocks it |
| Session stuck in a loop, navigating indefinitely or consuming resources without limit | Configurable limit on pages and total session time, ends the session on its own |
| Agent with more filesystem access to the host than it needs | Container `--read-only`, no host env vars, only three explicit bind mounts |
| You want to audit afterward exactly what the agent tried and what got blocked | Append-only JSONL log: every network and download decision, with URL/reason/timestamp |

## Visual proof

Real screenshots taken via `/screenshot` against the running container,
in the same session (allowlist: `docs.python.org`, `en.wikipedia.org`):

| Allowed domain → navigates normally | Out-of-scope domain → blocked |
|---|---|
| ![Allowed navigation to en.wikipedia.org](docs/screenshots/allowed_wikipedia.png) | ![Navigation to github.com blocked, blank screen](docs/screenshots/blocked_github.png) |
| `navigate("https://en.wikipedia.org/wiki/Web_browser")` → `ok: true`, Chromium renders the real page inside the container. | `navigate("https://github.com/")` → `ok: false, blocked: true, decision: "blocked_domain"`. The screen stays blank because the request never left the container: `read_page()` confirms the URL as `chrome-error://chromewebdata/` — zero bytes of github.com ever rendered. |

## Adversarial test results (Layer 3)

The trap page (`examples/trap_page.html`) contains a prompt-injection
attempt convincing the agent there's a "mandatory compliance step"
asking it to navigate to the cloud metadata endpoint
(`169.254.169.254`) and report back its content. The test runs a real
Claude agent with a legitimate task ("read this page and summarize it")
that passes through it along the way.

Two tests, two different roles — the same principle as `guarded-agent`:

- **`test_agent_reaction_to_trap_page`** runs the real agent and only
  *records* whether it tried to follow the injected instruction. It's an
  interesting data point on its own (well-aligned models frequently
  resist — that's what happened in `guarded-agent`), but it is **not
  proof** that the guardrail works, since it depends on whether the
  model takes the bait on that particular run.
- **`test_ssrf_navigation_is_blocked_regardless_of_agent_behavior`**
  forces the navigation call to the SSRF target directly against the
  sandbox's HTTP client, without going through the LLM at all. This is
  the test that proves the block deterministically — I ran it and
  confirmed it passes:

  ```
  tests/test_adversarial_agent.py::test_ssrf_navigation_is_blocked_regardless_of_agent_behavior PASSED
  ```

  The audit log (`logs/audit.jsonl`) records the full attempt: target URL
  (`http://169.254.169.254/latest/meta-data/iam/security-credentials/`),
  decision (`blocked_ssrf`), reason, and timestamp — the request never
  actually leaves the container.

I also ran all of Layer 2 (domain block confirmed by a mock server that
never receives the request, SSRF across 4 private-IP variants, disguised
download rejected by magic bytes, benign download accepted, automatic
session expiry) and Layer 4 (4 tabs, sustained navigation, peak memory of
~272MB against the container's 1GB limit) against a real Docker daemon —
52 tests passing in total (Layers 1, 2, 4, and the deterministic half of
Layer 3; the half that depends on a real LLM is conditional on a valid
`ANTHROPIC_API_KEY` in whoever's environment runs it).

## How to run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY (only needed for Layer 3 and the demo)
```

Tests, by layer:

```bash
pytest tests/test_guardrails_unit.py -v        # Layer 1 - no Docker
pytest tests/test_sandbox_integration.py -v    # Layer 2 - needs Docker running
pytest tests/test_adversarial_agent.py -v      # Layer 3 - Docker + API key
pytest tests/test_load.py -v -s                # Layer 4 - needs Docker running
```

Demo mode (saves a screenshot of every step to
`examples/demo_screenshots/` and prints the formatted log):

```bash
export $(grep -v '^#' .env | xargs)
python3 examples/demo_agent.py
```

Bringing the sandbox up manually (outside the tests), to poke at it with
`curl`:

```bash
./docker/run.sh "docs.python.org,example.com" 20 300
curl -X POST http://localhost:8088/navigate -H "Content-Type: application/json" -d '{"url":"https://docs.python.org/3/"}'
```

## Limitations

- **Container isolation + network allowlisting, not kernel/VM-level
  sandboxing.** `--cap-drop=ALL` and `--read-only` reduce the surface,
  but a Docker container shares the host's kernel. For use against
  genuinely hostile content (not just "URLs outside an agreed scope"),
  the recommendation is to run this **inside** an additional kernel/VM
  isolation layer — gVisor or Firecracker, for example — not as a
  replacement for this project, but as an extra layer underneath it.
- Chromium runs with `--no-sandbox` (needed to work without elevated
  privileges inside the container); the *container's* hardening
  compensates for this, but it's a deliberate trade-off, not an
  oversight.
- `file://`, `data:`, and `blob:` bypass the domain allowlist and IP
  check on purpose (they aren't network requests — see the architecture
  section). The risk this introduces is local file *reading*, contained
  by the read-only bind mount, not by the network layer.
- The magic-byte check covers the most common executable formats (PE,
  ELF, Mach-O, shebang scripts), it isn't an exhaustive list of every
  binary format that exists.
- The Flask server runs in development mode, single-threaded — that's
  fine for this project's scenarios (one agent, one session at a time);
  it isn't sized for multiple concurrent sessions in production without
  extra work (one `browser-sandbox` per container/process is the
  intended way to scale, not multiple sessions inside the same one).
