"""
Replanner: recebe o grafo atual, os resultados dos nos done, e uma nova
instrucao do usuario, e devolve um diff estrutural do grafo (nos pending
para remover, nos novos para adicionar, nos pending para modificar a
description). O diff e aplicado por `TaskGraph.apply_diff`, que e onde a
invariante "nunca mexe em done" e realmente garantida - este modulo so
pede o diff ao modelo, nao confia cegamente nele.
"""

import anthropic

from .task_graph import TaskGraph

PROPOSE_DIFF_TOOL = {
    "name": "propose_plan_diff",
    "description": (
        "Propoe um diff estrutural do grafo de tarefas para incorporar a nova instrucao do "
        "usuario. So pode afetar tarefas com status 'pending' - tarefas 'done' sao imutaveis "
        "e qualquer tentativa de remove-las ou modifica-las sera rejeitada de qualquer forma."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "remove_pending": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ids de tarefas pending que nao fazem mais sentido e devem ser removidas",
            },
            "modify_pending": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string", "description": "nova description da tarefa"},
                        "deps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "opcional: nova lista COMPLETA de deps desta tarefa. Use isto sempre que a "
                                "tarefa modificada deva passar a esperar por uma tarefa nova adicionada neste "
                                "mesmo diff (ex: um comparativo que agora tambem depende de uma pesquisa nova)."
                            ),
                        },
                    },
                    "required": ["id", "description"],
                },
                "description": "tarefas pending cuja description (e, se necessario, deps) deve mudar para refletir a nova instrucao",
            },
            "add_nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "deps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ids de tarefas ja existentes no grafo (done ou pending) ou de outra tarefa nova deste mesmo diff",
                        },
                    },
                    "required": ["id", "description", "deps"],
                },
                "description": "novas tarefas necessarias para atender a instrucao",
            },
        },
        "required": ["remove_pending", "modify_pending", "add_nodes"],
    },
}

SYSTEM_PROMPT = """Voce e um replanejador de tarefas. O usuario esta injetando uma nova \
instrucao NO MEIO da execucao de um plano existente. Sua tarefa e propor um diff minimo do \
grafo de tarefas que incorpora essa instrucao, atraves da ferramenta propose_plan_diff.

Regras rigidas:
- Tarefas com status 'done' ja foram executadas e seus resultados sao definitivos - voce NAO \
pode remove-las nem modifica-las, mesmo que a nova instrucao pareca contradize-las. Se for o \
caso, adicione uma nova tarefa que ajusta/complementa o resultado anterior, em vez de tentar \
apagar o que ja foi feito.
- So tarefas 'pending' podem ser removidas ou ter a description alterada.
- Novas tarefas devem ter deps apontando so para tarefas que ja existem no grafo (done ou \
pending) ou para outra tarefa nova deste mesmo diff.
- IMPORTANTE: se voce adicionar uma tarefa nova E uma tarefa pending existente deveria esperar \
o resultado dela antes de rodar (por exemplo, um comparativo que agora precisa incluir mais um \
item pesquisado), voce PRECISA incluir essa tarefa pending em modify_pending com o campo deps \
atualizado (a lista COMPLETA de deps, incluindo as antigas), nao so mudar a description. Uma \
tarefa cuja description menciona algo que ela nao tem como dep nunca vai ver o resultado disso.
- Seja minimo: nao reestruture o plano inteiro por uma instrucao pequena. So mude o que \
precisa mudar."""


def _format_graph_for_prompt(graph: TaskGraph) -> str:
    lines = [f"Objetivo original: {graph.objective}", ""]
    lines.append("Tarefas concluidas (done - IMUTAVEIS):")
    for node in graph.done_nodes():
        result_preview = (node.result or "")[:200]
        lines.append(f"  - [{node.id}] {node.description} -> resultado: {result_preview}")

    lines.append("")
    lines.append("Tarefas pendentes (podem ser removidas/modificadas):")
    for node in graph.nodes.values():
        if node.status == "pending":
            lines.append(f"  - [{node.id}] {node.description} (deps: {node.deps})")

    lines.append("")
    lines.append("Tarefas em execucao agora (nao tocar):")
    for node in graph.nodes.values():
        if node.status == "running":
            lines.append(f"  - [{node.id}] {node.description}")

    return "\n".join(lines)


def replan(graph: TaskGraph, new_instruction: str, client: anthropic.Anthropic, model: str) -> dict:
    prompt = (
        f"{_format_graph_for_prompt(graph)}\n\n"
        f"NOVA INSTRUCAO DO USUARIO (injetada agora, no meio da execucao):\n{new_instruction}\n\n"
        "Proponha o diff necessario via propose_plan_diff."
    )

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[PROPOSE_DIFF_TOOL],
        tool_choice={"type": "tool", "name": "propose_plan_diff"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input
