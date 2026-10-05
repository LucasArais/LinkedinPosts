# scoped-memory

🇧🇷 Português | [🇺🇸 English](README.en.md)

Memória de agente com **particionamento real por usuário e por time** — e
um teste automatizado que prova que a memória de um usuário nunca vaza
para outro, mesmo quando os dois conversam com **o mesmo agente, na mesma
sessão**, e mesmo quando estão **no mesmo time**.

Portfólio, quinta peça de uma série sobre contenção e controle de
agentes autônomos: [guarded-agent](../guarded-agent/) (circuit breaker
de ferramentas), [browser-sandbox](../browser-sandbox/) (browser
isolado), [steerable-agent](../steerable-agent/) (replanejamento em
runtime), [mistake-memory](../mistake-memory/) (memória episódica com
enforcement). Esta é sobre **quem pode ver o quê** na memória do agente.

**Autor:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Arquitetura

```
scoped-memory/
├── scoped_memory/
│   ├── store.py          # MemoryStore - SQLite, o filtro de escopo mora no SQL
│   ├── orchestrator.py   # sessão de chat com usuário ativo trocável + extractor de memória
│   ├── llm.py            # cliente OpenRouter (SDK openai, sem framework de agente)
│   └── display.py        # apresentação no terminal (rich)
├── main.py               # CLI interativa (/user, /team, /whoami, /memories)
└── tests/
    ├── test_store.py     # o teste de vazamento + regras de time
    └── test_session.py   # trocar de usuário na mesma sessão não mistura contexto
```

### Onde o isolamento mora (e onde ele NÃO mora)

Uma única tabela:

| coluna | exemplo |
|---|---|
| `id` | 1 |
| `scope_type` | `user` ou `team` (CHECK no schema) |
| `scope_id` | `alice`, `bob`, `eng` |
| `content` | "Alice disse que o código do cofre é ..." |
| `created_at` | ISO-8601 UTC |

O isolamento **não depende do modelo** e não é um filtro em Python
aplicado depois de uma busca global. Ele está na cláusula `WHERE` do
**único** método que lê o banco (`MemoryStore._visible`):

```sql
WHERE (scope_type = 'user' AND scope_id = :user_id)
   OR (scope_type = 'team' AND scope_id = :team_id)
```

Não existe `search_all`, não existe leitura sem `user_id`. Sem `team_id`,
só a primeira metade da cláusula roda. `user_id`/`team_id` vazios são
rejeitados (em vez de virarem um filtro que casa com nada — ou com tudo).
O ranking por relevância roda **sobre o resultado já filtrado**, nunca
antes.

### Memória de time é explícita

`add(content, user_id, team_id=None)` sempre grava a linha pessoal. Só se
`team_id` for passado é que uma **segunda** linha `scope_type=team` é
gravada. Nada é promovido de pessoal para time automaticamente.

No chat, quem decide o escopo é um extractor (chamada de LLM separada,
depois de cada resposta). Mas o LLM não tem a palavra final: o
`Orchestrator` só aceita `scope=team` se o usuário **tiver um time ativo**
**e** tiver dito explicitamente na mensagem que aquilo é pro time
(`time`, `equipe`, `team` — regex determinística, fora do modelo).

### Por que o histórico de chat também é particionado

Particionar só a memória persistida não basta. Se o `Orchestrator`
mantivesse **uma** lista de mensagens para a sessão, o segredo que a
alice contou estaria no histórico enviado ao modelo quando o bob fizesse
a próxima pergunta — o vazamento nem passaria pelo banco. Por isso o
histórico (e o time ativo) é guardado **por `user_id`** dentro da sessão:
`/user bob` começa do zero, `/user alice` de volta restaura a conversa
dela.

## Setup

```bash
cd scoped-memory
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # e coloque sua OPENROUTER_API_KEY
```

O modelo padrão é `qwen/qwen3.8-27b:free` no [OpenRouter](https://openrouter.ai).
Modelos `:free` dão rate limit (429) com frequência e às vezes devolvem
resposta vazia; o cliente cai automaticamente para os modelos de
`OPENROUTER_FALLBACK_MODELS`, em ordem.

```bash
python main.py              # usa memory.db
python main.py --db demo.db # banco separado pra gravar a demo
```

## Roteiro da demo (gravável)

Comece com um banco limpo: `rm -f demo.db && python main.py --db demo.db`

**1. Alice conta um segredo**

```
> /user alice
alice > Guarda um segredo: o codigo do cofre da sala 3 e 4815-1623. Nao conta pra ninguem.
  ✚ memoria gravada (user): Alice ... o código do cofre da sala 3 é 4815-1623 ...
alice > /memories            # mostra a linha user:alice
```

**2. Bob pergunta sobre o segredo da alice — o agente não sabe**

```
alice > /user bob
bob > Qual e o codigo do cofre que a alice te contou?
  agente: Não tenho nenhuma memória sobre um código de cofre ...
bob > /memories              # "nenhuma"
```

**3. Os dois entram no time `eng` — memória de time aparece pros dois**

```
bob > /team eng
bob@eng > /memories          # ainda não vê o segredo da alice, mesmo time
bob@eng > /user alice
alice > /team eng
alice@eng > Isso e pro time: o deploy de sexta esta congelado ate a migracao terminar.
  ✚ memoria gravada (team): Alice informou que o deploy de sexta está congelado ...
alice@eng > /user bob
bob@eng > Tem alguma restricao de deploy essa semana?
  agente: Sim. Alice informou que o deploy de sexta está congelado ...
bob@eng > /memories          # só team:eng — o segredo pessoal da alice continua fora
bob@eng > /quit
```

**4. Teste de vazamento ao vivo**

```bash
pytest -v
```

Os testes são determinísticos e rodam sem rede (o isolamento é uma
propriedade do SQL, não do modelo). Destaques:

- `test_leak_alice_personal_memory_never_reaches_bob` — bob busca com a
  frase **exata** do segredo da alice e não recebe nada.
- `test_leak_same_team_does_not_expose_personal_memory` — mesmo
  `team_id` não abre memória pessoal de outro membro.
- `test_leak_many_users_only_ever_see_their_own` — 20 usuários no mesmo
  time, cada um só vê o próprio pessoal + o do time.
- `test_leak_sql_injection_in_user_id_does_not_widen_scope`
- `test_team_memory_visible_to_both_members`
- `test_switching_user_does_not_leak_memory_or_history` — com um
  `FakeLLM` que grava cada prompt, prova que **nenhum byte** do segredo
  da alice aparece no que seria enviado ao modelo quando o bob pergunta
  (nem via memória, nem via histórico).

## Limitações (é um MVP)

- Ranking por sobreposição de palavras, não embeddings — o projeto é
  sobre isolamento, não retrieval. Embeddings entrariam **depois** do
  filtro de escopo.
- Identidade é o que o `/user` diz: não há autenticação. Em produção o
  `user_id` viria de um token verificado, nunca do texto do usuário.
- Pertencimento a time não é validado (qualquer um pode `/team eng`);
  em produção, `team_id` só seria aceito se o usuário for membro.
- O extractor pode errar ao resumir o fato — mas não consegue mudar o
  escopo para `team` sem o marcador explícito na mensagem do usuário.
