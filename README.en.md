# LinkedinPosts

[🇧🇷 Português](README.md) | 🇺🇸 English

Demos, experiments and proofs of concept I build to go along with my
LinkedIn posts about AI, Cloud, Data and Software Engineering. Each folder
in this repo is an independent, self-contained project — think of it as a
public journal of things I'm exploring, not a single product.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Lucas%20Arais-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/lucas-arais/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Projects

| Project | Description | Stack |
|---|---|---|
| [guarded-agent](guarded-agent/) | Autonomous LLM-based agent (Claude + tool calling) with a model-independent guardrails/circuit-breaker layer: per-task tool allowlist, call limit, kill switch, and JSONL audit log. | Python, Anthropic API |
| [browser-sandbox](browser-sandbox/) | Headless browser (Playwright) isolated in a Docker container, controlled by an agent via tool calling: domain allowlist, SSRF/private-IP blocking, download checks by magic bytes, and session limits. Packaged as a real pip package, with ready-made adapters for Anthropic and LangChain. | Python, Playwright, Docker, LangChain, Anthropic API |
| [steerable-agent](steerable-agent/) | Orchestrator that executes a plan as a persisted task graph (DAG) and accepts injected instructions at runtime — via an `inbox/` folder — without losing work already completed. The safety invariant (completed nodes are immutable) is enforced outside the model and backed by tests. | Python, Anthropic API, rich |
| [mistake-memory](mistake-memory/) | Episodic memory for agents: records approach, outcome, and failure reason, and actively blocks repeating an already-rejected approach after 3 fails — even when the model itself argues this time would be different. Local embedding search, enforcement outside the model. | Python, SQLite, sentence-transformers, Anthropic API |

Each project has its own `README.md` with architecture, design decisions,
and instructions on how to run it — start there.

## How this repo works

It's a public repository, but only I (the owner) have permission to push
directly to `main`. Anyone else can:

- **Fork it** and use the code however they like (it's MIT, see the
  [license](#license) below);
- **Open a Pull Request** with suggestions, fixes, or improvements — every
  change to `main`, including my own, goes through a PR (branch protection
  is on).

This isn't a project that accepts feature contributions by default — it's
more of a shared collection of demo code — but if you find a bug or have a
suggestion, a PR or an issue is very welcome.

## Structure

```
LinkedinPosts/
├── guarded-agent/     # project 1: autonomous agent with guardrails
├── browser-sandbox/   # project 2: sandboxed browser for agents
├── steerable-agent/   # project 3: task-graph orchestrator with runtime replanning
├── mistake-memory/    # project 4: episodic memory with blocking enforcement
├── ...                # future projects land here, one folder each
└── README.md          # this file
```

## License

[MIT](LICENSE) — use, copy, and adapt the code freely, with attribution.

## Connect

The posts that go along with these projects are published on my LinkedIn:
**[linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)**
