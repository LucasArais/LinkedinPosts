# steerable-agent

🇧🇷 Português | [🇺🇸 English](README.en.md)

Um orquestrador de agente que executa um plano como um **grafo de tarefas
persistido** e aceita **injeção de novas instruções em tempo de
execução**, sem perder o trabalho já concluído.

Projeto de portfólio, terceira peça de uma série sobre contenção e
controle de agentes autônomos. As duas primeiras foram
[guarded-agent](../guarded-agent/) (circuit breaker para chamadas de
ferramenta) e [browser-sandbox](../browser-sandbox/) (browser isolado em
container). Esta é sobre um problema diferente: agentes de execução longa
não podem ser caixas-pretas que só aceitam instrução no início — o
usuário precisa conseguir **direcionar o trabalho no meio do caminho**
sem jogar fora o que já foi feito.

**Autor:** Lucas Arais — [linkedin.com/in/lucas-arais](https://www.linkedin.com/in/lucas-arais/)

## Arquitetura

```
steerable-agent/
├── steerable_agent/
│   ├── task_graph.py    # TaskGraph/TaskNode - o DAG persistido + a invariante de seguranca
│   ├── planner.py        # objetivo em texto -> TaskGraph inicial (3-6 nos)
│   ├── replanner.py      # (grafo, nova instrucao) -> diff estrutural
│   ├── orchestrator.py   # o loop principal
│   └── display.py        # apresentacao no terminal (rich) - sem logica de decisao
├── main.py                # CLI
├── inbox/                 # solte um .txt aqui para injetar uma instrucao
├── checkpoint.json         # criado em runtime - o estado do grafo persistido
└── tests/
    └── test_task_graph.py  # 22 testes deterministicos da invariante de seguranca
```

### O grafo (`TaskGraph`)

Cada nó tem `id`, `description`, `status`
(`pending` / `running` / `done` / `blocked`), `deps` (lista de ids) e
`result`. O grafo inteiro serializa para `checkpoint.json` após **cada**
nó concluído — não só no final. Isso é o que torna a execução retomável:
se o processo morrer, `python main.py` (sem objetivo) na próxima vez
carrega o checkpoint e continua exatamente de onde parou, sem
re-executar nada que já estava `done`.

### O loop (`Orchestrator`)

```
enquanto o grafo nao estiver completo:
    verifica ./inbox/*.txt
        se existir arquivo -> le, apaga, chama o replanner, aplica o diff, persiste
    pega o proximo no "pending" cujas deps estao todas "done"
    marca "running", persiste
    chama a Anthropic API para executar a tarefa desse no
    marca "done" com o resultado, persiste
```

A checagem da inbox acontece **antes de cada nó**, não em paralelo — é
uma decisão deliberada: o replan nunca interrompe um nó no meio da
execução, só entra na fresta entre um nó terminar e o próximo começar.

### A invariante de segurança (`TaskGraph.apply_diff`)

O replanner é uma chamada de LLM — não confiável por padrão, no mesmo
espírito dos projetos irmãos. O diff que ele devolve passa por
`apply_diff`, que **recusa** qualquer tentativa de remover ou modificar
um nó que não esteja com status `pending`:

```python
if node.status != PENDING:
    result.rejected.append(f"... recusado - status e '{node.status}', so 'pending' pode ser removido")
    continue  # o no continua exatamente como estava
```

Isso é reforçado por teste, não só por prompt: `test_diff_cannot_remove_done_node`
e `test_diff_cannot_modify_done_node` constroem um grafo com um nó `done`,
mandam um diff tentando apagá-lo/reescrevê-lo, e verificam que o nó
continua intocado e a tentativa aparece em `result.rejected` — igual ao
princípio dos outros dois projetos: a prova real é o teste que força o
cenário, não a suposição de que o modelo vai se comportar.

Efeito colateral tratado: se um nó pending é removido e outro nó pending
dependia dele, esse dependente não fica preso num limbo silencioso — é
marcado `blocked` automaticamente (`mark_blocked_dangling`), e aparece
assim na tabela do terminal.

### Um bug real encontrado na primeira validação ao vivo

`modify_pending` originalmente só deixava mudar a `description` de um nó
— exatamente como pedido. Na primeira execução real do cenário abaixo, o
replanner adicionou a tarefa de pesquisar o Zoho e reescreveu a
description de `comparativo` para mencioná-lo, mas **a tarefa de
comparação rodou sem esperar a pesquisa do Zoho terminar** — porque
"esperar" só existe via `deps`, e nada no diff atualizava isso. O
resultado final citava o Zoho na descrição da tarefa, mas o texto gerado
nunca via os dados de verdade.

Corrigido estendendo `modify_pending` para aceitar um `deps` opcional
(reordenando `apply_diff` para processar `add_nodes` antes, e com uma
checagem de ciclo via DFS), e reforçando o system prompt do replanner
para exigir isso explicitamente. Re-rodei o mesmo cenário depois do fix e
confirmei no `checkpoint.json`: `comparativo` passou a depender de
`[n1, n2, n3, n5]` (o `n5` sendo a pesquisa do Zoho recém-criada), e o
texto final realmente incorpora os dados de preço do Zoho. Ficou como
regressão em `test_diff_modify_pending_can_add_new_dependency`.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
```

```bash
python main.py "pesquise 3 concorrentes de um produto SaaS de CRM e escreva um comparativo"
```

Isso gera um plano inicial (painel + tabela colorida no terminal) e
começa a executar nó por nó, com um painel amarelo em "iniciando" e verde
em "concluído" para cada um.

## Cenário de teste manual: injetando uma instrução no meio da execução

Este é o roteiro que gravei para a demo (funciona bem em GIF/screenshot —
o `rich` colore cada tipo de evento diferente: ciano para o banner
inicial, amarelo para execução, verde para conclusão, magenta para o
replan).

**1. Terminal 1 — inicia o agente:**

```bash
python main.py "pesquise 3 concorrentes de um produto SaaS de CRM (ex: HubSpot, Pipedrive, Salesforce) e escreva um comparativo final"
```

O plano inicial normalmente sai parecido com:

```
n1: Pesquisar HubSpot (deps: [])
n2: Pesquisar Pipedrive (deps: [])
n3: Pesquisar Salesforce (deps: [])
n4: Compilar dados de mercado dos 3 (deps: [n1, n2, n3])
n5: Escrever comparativo final (deps: [n4])
```

**2. Deixe rodar até o primeiro nó (`n1`) terminar** — vai aparecer o
painel verde "concluído". É o momento certo para injetar a instrução,
porque já existe pelo menos um nó `done` (prova visual de que ele não vai
ser tocado pelo replan).

**3. Terminal 2 (enquanto o Terminal 1 continua rodando) — injete a instrução:**

```bash
echo "priorize também o preço de cada concorrente no comparativo, e adicione o Zoho CRM na pesquisa" > inbox/instrucao1.txt
```

**4. Volte pro Terminal 1.** Antes de pegar o próximo nó pronto, o
orchestrator detecta o arquivo, mostra o painel magenta "NOVA INSTRUÇÃO
RECEBIDA" com o conteúdo exato que foi injetado, chama o replanner, e
imprime o diff aplicado — algo como:

```
+ adicionado   n6: Pesquisar Zoho CRM (deps: [])
~ modificado   n5: description e deps atualizadas (agora inclui n6 como dependencia)
```

Repare que `n1` (já `done`) não aparece em lugar nenhum do diff — o
replanner nem tenta tocar nele, e mesmo que tentasse, `apply_diff`
recusaria.

**5. A execução continua** normalmente pelos nós restantes, agora
incluindo `n6` (a pesquisa do Zoho que não existia no plano original) e
com `n5` reescrito para incluir preço.

**6. Teste de retomada (opcional, mas vale mostrar):** interrompa o
processo no meio (`Ctrl+C`) depois de alguns nós `done`, e rode de novo
**sem passar objetivo**:

```bash
python main.py
```

Ele carrega o `checkpoint.json`, mostra "retomando checkpoint existente"
no banner, e continua exatamente dos nós que ainda estavam `pending` —
os `done` não são re-executados.

## Testes automatizados

```bash
pytest tests/ -v
```

22 testes, todos determinísticos (sem chamada de API): navegação do
grafo (`next_ready_node`, `is_stuck`), a invariante de segurança completa
de `apply_diff` (remoção/modificação de done é recusada, running é
recusada, deps inválidas em `add_nodes` são recusadas, ids duplicados são
recusados, dependentes de um nó removido ficam `blocked`, `modify_pending`
pode adicionar uma nova dependência mas não pode criar um ciclo), e
round-trip de serialização em disco.

## Limitações

- Execução sequencial de um nó por vez — não paralelizamos nós
  independentes que poderiam rodar ao mesmo tempo (ex: `n1`, `n2`, `n3`
  do exemplo acima não têm dependência entre si). Seria uma extensão
  natural, mas complica a história do checkpoint (persistir estado
  parcial de N nós rodando ao mesmo tempo) e não era o foco deste MVP.
- A inbox só é checada entre nós, não durante a execução de um nó em si —
  uma instrução injetada demora, na pior das hipóteses, o tempo de uma
  chamada de API para ser notada.
- `_execute_node` não tem acesso a ferramentas (shell, browser, etc) —
  cada nó é uma única chamada de texto à API. Combinar isso com os
  guardrails de `guarded-agent`/`browser-sandbox` para dar tool calling
  real a cada nó é a extensão óbvia, não implementada aqui.
- `add_nodes` não precisa de checagem de ciclo explícita porque a
  restrição estrutural (novas dependências só apontam para nós que já
  existiam antes do diff ou vieram antes no mesmo diff) já torna um ciclo
  impossível de introduzir por construção. `modify_pending` com `deps` é
  o único caminho que pode reintroduzir uma aresta livre o suficiente
  para formar um ciclo, e por isso é o único que roda uma checagem DFS
  explícita (`_creates_cycle`).
