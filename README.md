# LinkedinPosts

🇧🇷 Português | [🇺🇸 English](README.en.md)

Demos, experimentos e provas de conceito de código que eu construo para acompanhar
meus posts no LinkedIn sobre IA, Cloud, Dados e Engenharia de Software. Cada pasta
neste repo é um projeto independente e autocontido — pense nisso como um diário
público de coisas que estou explorando, não um produto único.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Lucas%20Arais-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/lucas-arais/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Projetos

| Projeto | Descrição | Stack |
|---|---|---|
| [guarded-agent](guarded-agent/) | Agente autônomo baseado em LLM (Claude + tool calling) com uma camada de guardrails/circuit breaker independente do modelo: allowlist de ferramentas por tarefa, limite de chamadas, kill switch e log de auditoria em JSONL. | Python, Anthropic API |
| [browser-sandbox](browser-sandbox/) | Browser headless (Playwright) isolado em container Docker, controlado por um agente via tool calling: allowlist de domínio, bloqueio de SSRF/IP privado, checagem de download por magic bytes e limites de sessão. Empacotado como pip package de verdade, com adapters prontos para Anthropic e LangChain. | Python, Playwright, Docker, LangChain, Anthropic API |

Cada projeto tem seu próprio `README.md` com arquitetura, decisões de design e
instruções de como rodar — comece por lá.

## Como este repo funciona

É um repositório público, mas só eu (owner) tenho permissão de dar push direto na
`main`. Qualquer outra pessoa pode:

- **Fazer fork** e usar o código como quiser (é MIT, ver [licença](#licença) abaixo);
- **Abrir um Pull Request** com sugestões, correções ou melhorias — toda mudança na
  `main`, inclusive as minhas, passa por PR (branch protection ativada).

Não é um projeto que aceita contribuições de feature por padrão — é mais um
compartilhamento de código de demos — mas se você achar um bug ou tiver uma
sugestão, um PR ou uma issue são muito bem-vindos.

## Estrutura

```
LinkedinPosts/
├── guarded-agent/     # projeto 1: agente autônomo com guardrails
├── browser-sandbox/   # projeto 2: browser sandboxed para agentes
├── ...                # próximos projetos entram aqui, uma pasta cada
└── README.md          # este arquivo
```

## Licença

[MIT](LICENSE) — use, copie e adapte o código à vontade, com atribuição.

## Conecte-se

Os posts que acompanham esses projetos saem no meu LinkedIn:
**[linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)**
