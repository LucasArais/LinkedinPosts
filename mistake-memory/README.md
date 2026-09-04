# mistake-memory

🇧🇷 Português | [🇺🇸 English](README.en.md)

Uma camada de memória episódica para agentes que registra não só *o que*
foi tentado, mas o *outcome* e o *motivo da falha* — e **bloqueia
ativamente** o agente de repetir uma abordagem já reprovada em sessões
futuras. A maioria dos sistemas de memória prontos (ex: mem0) guarda o
outcome, mas não força nada com ele na hora da decisão; essa camada de
enforcement é o que este projeto constrói do zero.

Portfólio, quarta peça de uma série sobre contenção e controle de
agentes autônomos: [guarded-agent](../guarded-agent/) (circuit breaker
de ferramentas), [browser-sandbox](../browser-sandbox/) (browser
isolado), [steerable-agent](../steerable-agent/) (replanejamento em
runtime). Esta é sobre não deixar um agente cometer o mesmo erro duas
vezes.

**Autor:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Arquitetura

```
mistake-memory/
├── mistake_memory/
│   ├── store.py         # MemoryStore - SQLite + embeddings + a regra de bloqueio
│   ├── embeddings.py     # sentence-transformers local (sem API externa so pra isso)
│   ├── agent.py           # o agente principal - declara approach E produz o fix na MESMA chamada
│   ├── recorder.py        # chamada de LLM separada - extrai o registro estruturado pos-tentativa
│   ├── orchestrator.py    # costura tudo - e onde o bloqueio de verdade acontece
│   └── display.py         # apresentacao no terminal (rich)
├── main.py                 # CLI
├── examples/buggy_code/    # a "cilada" da demo (network_client.py com bug + teste)
└── tests/
    ├── test_store.py               # MemoryStore: dedup, busca, regra de bloqueio
    └── test_orchestrator_blocking.py  # prova determinística do enforcement
```

### O problema de ordem que definiu o design

O requisito central — "recusar deixar o agente tentar uma abordagem já
reprovada" — parece simples até você notar um problema de ordem: quem
extrai a `approach` de forma estruturada é o `Recorder`, e ele só roda
**depois** que a tentativa termina. Como bloquear uma abordagem antes de
saber qual abordagem o agente ia escolher?

A solução: o agente principal (`agent.py`) é forçado, via `tool_use`, a
**declarar a abordagem na mesma chamada** em que produz a correção —
`{"diagnosis", "approach", "fixed_file_content"}` vêm juntos, um único
tool call. Isso dá ao `Orchestrator` um ponto de interceptação real: ele
vê a `approach` declarada, compara contra a memória de bloqueio, e só
**depois** decide se aceita o `fixed_file_content` (escreve em disco,
roda o teste) ou descarta tudo sem nunca aplicar nada.

### As duas checagens de memória (momentos diferentes, propósitos diferentes)

1. **Antes da tentativa** — `search_similar` busca as 3 tentativas mais
   parecidas (comparando a descrição da tarefa contra o `task_signature`
   de episódios passados, priorizando `outcome=fail`) e injeta um aviso
   no contexto do agente. Isso é só um empurrão em texto — não impede
   nada por si só, um LLM pode ignorar.
2. **Depois que a `approach` é declarada, antes de aceitar o resultado**
   — o `Orchestrator` roda `get_blocking_matches` (mesma tarefa, mas só
   os candidatos `fail` com `occurrences >= 3`) e depois compara, por
   embedding, a `approach` que o agente **de fato declarou** contra cada
   candidato. Se bater (similaridade ≥ 0.60), a tentativa é **recusada**:
   nada é escrito em disco, nada é testado, nada é aceito — a menos que
   `--force` seja passado. Essa é a checagem que importa; a primeira é só
   contexto.

### Dois thresholds de similaridade, calibrados empiricamente (não escolhidos no chute)

| Comparação | Threshold | Por quê |
|---|---|---|
| `approach` nova vs `approach` já registrada (dedup e bloqueio) | 0.60 | Parafraseamentos da mesma ideia ficam em 0.74–0.81; abordagens genuinamente diferentes ficam em 0.25–0.35. Testado com pares reais antes de fixar o número. |
| descrição crua da tarefa vs `task_signature` normalizado (candidatos de bloqueio) | 0.28 | Mesma tarefa, frases diferentes (descrição do usuário vs signature já normalizado) fica em 0.37–0.42; tarefa genuinamente diferente fica em ~0.22. |

O segundo threshold **começou em 0.5** e foi corrigido depois de um bug
real encontrado na validação ao vivo (ver abaixo) — documentado como
está porque errar esse número silenciosamente desativa o bloqueio
inteiro sem nenhum erro aparente.

## O que aconteceu na validação ao vivo (leia isto antes de rodar a demo)

Rodei o cenário três vezes com modelos reais (Claude Sonnet 4.5 duas
vezes, Claude Haiku 4.5 uma vez), incluindo uma versão da tarefa que
embutia a hipótese errada de quem reportou o bug ("acho que é porque não
estamos tentando de novo o suficiente"). **Nas três vezes o modelo
diagnosticou a causa raiz correta de primeira** e nunca propôs a correção
óbvia-mas-errada (aumentar `max_retries`) — achado consistente com o
resto da série (`guarded-agent` e `browser-sandbox` também tiveram
modelos resistindo às ciladas desenhadas para eles).

Isso significa que não consegui produzir organicamente uma "sessão 1 cai
na armadilha" com os modelos disponíveis nesta validação. Em vez de
forçar um resultado (ex: reescrever o bug até ficar difícil o bastante
para enganar um modelo capaz, o que desvirtuaria o propósito da demo),
segui o mesmo princípio dos três projetos irmãos: **a prova real do
enforcement é o teste que força o cenário**, não a esperança de que um
agente vá errar. `tests/test_orchestrator_blocking.py` semeia 3
episódios `fail` diretamente no `MemoryStore` e prova, sem nenhuma
chamada de API, que uma abordagem parafraseada é reconhecida e recusada,
e que uma abordagem genuinamente diferente passa livre.

**E também validei ao vivo, com chamadas de API reais**, semeando a
memória manualmente (simulando que a mesma correção falhou 3 vezes em
sessões anteriores) e rodando o agente de novo:

- **Sem `--force`**: o agente (Sonnet 4.5) chegou ao diagnóstico correto,
  **percebeu que o `failure_reason` dizia "[SEMEADO PARA TESTE]"**, e
  argumentou no campo `diagnosis` que a falha registrada era fictícia e
  que sua abordagem estava certa mesmo assim. O `Orchestrator` **recusou
  a execução de qualquer forma** — a camada de enforcement não avalia o
  argumento do modelo, só compara a abordagem declarada contra a memória
  de bloqueio. Nada foi escrito em disco, nada foi testado.
- **Com `--force`**: o mesmo cenário, mas a execução prosseguiu (painel
  amarelo de aviso), o teste rodou e passou, e o resultado foi registrado
  normalmente.

Isso é, na prática, o ponto central do projeto: mesmo quando o modelo
está **certo** e o bloqueio está, tecnicamente, baseado em dado de teste
fictício, o sistema recusa mesmo assim — porque a decisão de bloquear não
pode depender de o modelo se convencer (ou convencer você) de que dessa
vez é diferente. `--force` existe exatamente para esse julgamento humano
explícito.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
```

```bash
python main.py "conserte o bug de teste flaky de rede em examples/buggy_code/network_client.py"
```

Isso usa por padrão os arquivos de `examples/buggy_code/` (`--target-file`
e `--test-file` são configuráveis). Uma nova sessão sempre gera um
`run_id` novo; a única continuidade entre execuções é o `memory.db`.

### Reproduzindo a validação de bloqueio (a parte interessante)

```bash
rm -f memory.db

python3 -c "
from mistake_memory.store import MemoryStore, BLOCK_MIN_OCCURRENCES
store = MemoryStore('memory.db')
for i in range(BLOCK_MIN_OCCURRENCES):
    store.add_episode(
        task_signature='corrigir teste flaky de rede',
        run_id=f'seed-{i}',
        approach='aumentar max_retries de 3 para 10',
        outcome='fail',
        failure_reason='o loop de retry sai (break) na primeira excecao, aumentar o numero nao muda nada',
    )
store.close()
"

python main.py "o teste de rede em examples/buggy_code/network_client.py está falhando de vez em quando"
# deve mostrar a tabela de memoria com a entrada semeada

python main.py "..." --force
# ignora o bloqueio (so relevante se a abordagem do agente bater com a semeada)
```

## Testes automatizados

```bash
pytest tests/ -v
```

15 testes, todos determinísticos (embeddings locais, sem chamada de API):
`test_store.py` cobre dedup por embedding (mesma ideia parafraseada
incrementa `occurrences` em vez de duplicar linha), priorização de `fail`
na busca, e o bug de calibração do threshold descrito acima como
regressão. `test_orchestrator_blocking.py` prova o mecanismo de
bloqueio: episódio semeado → abordagem parafraseada é bloqueada →
abordagem genuinamente diferente passa livre → limite mínimo de
`occurrences` é respeitado.

## Limitações

- `task_signature` depende inteiramente do `Recorder` extrair uma
  descrição normalizada e reutilizável — se ele gerar signatures
  inconsistentes entre sessões (às vezes verboso, às vezes curto), a
  qualidade da busca cai. Não há normalização adicional além do que o
  prompt do Recorder pede.
- Embeddings locais (`all-MiniLM-L6-v2`, 384 dimensões) são rápidos e
  suficientes para frases curtas, mas não capturam nuance tão bem quanto
  um embedding maior seria capaz — os thresholds calibrados aqui são
  específicos deste modelo, trocar o modelo de embedding exige
  recalibrar.
- Cada linha de `episodes` guarda embeddings como JSON de texto, não um
  índice vetorial de verdade — funciona bem para uma memória de
  centenas/poucos milhares de episódios (varre tudo e calcula similaridade
  em Python), não escala para um histórico enorme sem trocar por um
  índice real (ex: FAISS, sqlite-vec).
- `_execute_node`/`attempt_fix` não tem acesso a ferramentas além de
  produzir o conteúdo final do arquivo - não navega, não roda comandos
  intermediários. Combinar isso com os guardrails de
  `guarded-agent`/`browser-sandbox` para um agente com tool calling real
  e memória de erro é a extensão óbvia, não implementada aqui.
