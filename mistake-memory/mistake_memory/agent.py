"""
O agente principal que tenta a tarefa. Deliberadamente forcado, via
tool_use, a DECLARAR a abordagem escolhida (`approach`) na mesma resposta
em que produz a correcao - isso e o que permite ao Orchestrator checar a
abordagem contra a memoria de bloqueio e recusar aceitar a tentativa
inteira antes de qualquer coisa ser aplicada. Se approach e fix viessem
em chamadas separadas (primeiro decide, depois escreve), o modelo poderia
"decidir" uma coisa e escrever outra sem nenhuma correspondencia
verificavel entre as duas.
"""

import anthropic

ATTEMPT_TOOL = {
    "name": "attempt_fix",
    "description": "Registra a abordagem escolhida para o bug e produz o arquivo corrigido.",
    "input_schema": {
        "type": "object",
        "properties": {
            "diagnosis": {
                "type": "string",
                "description": "O que voce acredita estar causando o problema, com base no codigo e no teste",
            },
            "approach": {
                "type": "string",
                "description": "Resumo curto (uma frase) da mudanca que voce vai fazer para corrigir o bug",
            },
            "fixed_file_content": {
                "type": "string",
                "description": "Conteudo COMPLETO do arquivo corrigido (o arquivo inteiro, nao um diff)",
            },
        },
        "required": ["diagnosis", "approach", "fixed_file_content"],
    },
}

SYSTEM_PROMPT = """Voce e um engenheiro de software corrigindo um bug. Vai receber o codigo com o \
bug e o teste que precisa passar. Diagnostique a causa raiz e produza o arquivo corrigido \
inteiro via attempt_fix. Se houver um bloco de memoria de tentativas anteriores no início da \
mensagem, leve a serio: nao repita uma abordagem ja marcada como fail sem antes explicar, no \
campo diagnosis, por que dessa vez seria diferente."""


def attempt_fix(
    task_description: str,
    file_content: str,
    test_content: str,
    memory_context: str,
    client: anthropic.Anthropic,
    model: str,
) -> dict:
    parts = []
    if memory_context:
        parts.append(memory_context)
    parts.append(f"Tarefa: {task_description}")
    parts.append(f"=== arquivo com bug ===\n{file_content}")
    parts.append(f"=== teste que precisa passar ===\n{test_content}")
    user_message = "\n\n".join(parts)

    response = client.messages.create(
        model=model,
        max_tokens=3072,
        system=SYSTEM_PROMPT,
        tools=[ATTEMPT_TOOL],
        tool_choice={"type": "tool", "name": "attempt_fix"},
        messages=[{"role": "user", "content": user_message}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input
