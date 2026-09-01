"""
Planner inicial: dado um objetivo em texto, gera o TaskGraph inicial (3-6
nos). Usa tool_use forcado (tool_choice) em vez de pedir JSON em texto
livre - a resposta ja vem estruturada e validada pelo schema, sem
depender de parsear texto solto do modelo.
"""

import json

import anthropic

from .task_graph import TaskGraph, TaskNode

CREATE_PLAN_TOOL = {
    "name": "create_plan",
    "description": "Cria o plano inicial de tarefas para atingir o objetivo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "minItems": 3,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "id curto e unico, ex: 'n1', 'pesquisa_concorrente_a'"},
                        "description": {"type": "string", "description": "o que essa tarefa deve fazer, especifico o suficiente para ser executada sozinha"},
                        "deps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ids de outras tarefas deste MESMO plano que precisam terminar antes desta comecar",
                        },
                    },
                    "required": ["id", "description", "deps"],
                },
            }
        },
        "required": ["nodes"],
    },
}

SYSTEM_PROMPT = """Voce e um planejador de tarefas. Dado um objetivo, decomponha-o em 3 a 6 \
tarefas concretas e executaveis, formando um grafo de dependencias (DAG - sem ciclos). \
Cada tarefa deve ser especifica o suficiente para ser executada de forma independente por \
outro processo que so vai ver a description dela (mais os resultados das tarefas das quais \
ela depende). Use ids curtos e unicos. So aponte uma dependencia quando a tarefa realmente \
precisar do resultado da outra."""


def create_initial_plan(objective: str, client: anthropic.Anthropic, model: str) -> TaskGraph:
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[CREATE_PLAN_TOOL],
        tool_choice={"type": "tool", "name": "create_plan"},
        messages=[{"role": "user", "content": f"Objetivo: {objective}"}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    nodes_data = tool_use.input["nodes"]

    graph = TaskGraph(objective=objective)
    known_ids = set()
    for entry in nodes_data:
        node_id = entry["id"]
        if node_id in known_ids:
            raise ValueError(f"planner devolveu id duplicado: '{node_id}'")
        deps = [d for d in entry.get("deps", []) if d in known_ids or d in {e["id"] for e in nodes_data}]
        graph.add_node(TaskNode(id=node_id, description=entry["description"], deps=deps))
        known_ids.add(node_id)

    return graph
