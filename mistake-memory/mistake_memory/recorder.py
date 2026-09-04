"""
Recorder: uma chamada de LLM SEPARADA do agente principal, que le a
transcricao da tentativa (diagnostico, abordagem, resultado real do teste)
e extrai um registro estruturado para a memoria episodica. E separada de
proposito - o agente que tentou a tarefa tem incentivo (mesmo que so
estatistico, do jeito que modelos preveem texto) a description a propria
tentativa de forma favoravel; uma chamada dedicada, so pra extrair o
registro a partir de evidencia observavel (o resultado real do teste,
nao a opiniao do agente sobre se funcionou), e o que faz o "nunca perder
o resultado junto da tentativa" ser confiavel.
"""

import anthropic

RECORD_TOOL = {
    "name": "record_episode",
    "description": "Extrai um registro estruturado de uma tentativa para a memoria episodica de agentes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_signature": {
                "type": "string",
                "description": (
                    "Descricao curta e normalizada do TIPO de problema (nao os detalhes especificos "
                    "desta execucao) - precisa ser reconhecivel para tarefas parecidas no futuro. "
                    "Ex: 'corrigir teste flaky de rede', nao 'corrigir test_fetch_with_retry_eventually_succeeds'."
                ),
            },
            "approach": {
                "type": "string",
                "description": "A abordagem que foi de fato tentada (reafirme com suas palavras, com base na transcricao)",
            },
            "outcome": {
                "type": "string",
                "enum": ["success", "fail"],
                "description": "Baseado no RESULTADO REAL informado na transcricao (ex: saida do pytest), nao na opiniao do agente sobre si mesmo",
            },
            "failure_reason": {
                "type": "string",
                "description": "Se outcome=fail: por que especificamente essa abordagem nao resolveu o problema real. Vazio se outcome=success.",
            },
        },
        "required": ["task_signature", "approach", "outcome"],
    },
}

SYSTEM_PROMPT = """Voce extrai um registro estruturado de uma tentativa de tarefa para a \
memoria episodica de um agente. Sua fonte de verdade sobre o outcome e o RESULTADO OBSERVAVEL \
relatado na transcricao (por exemplo, se um teste automatizado passou ou falhou de verdade), \
nunca a auto-avaliacao do agente que tentou a tarefa. Se outcome for 'fail', failure_reason \
precisa ser especifico o suficiente para impedir que a mesma abordagem seja tentada de novo \
sem se perceber - descreva o mecanismo real da falha, nao so 'nao funcionou'."""


def record_attempt(transcript: str, client: anthropic.Anthropic, model: str) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[RECORD_TOOL],
        tool_choice={"type": "tool", "name": "record_episode"},
        messages=[{"role": "user", "content": f"Transcricao da tentativa:\n\n{transcript}"}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input
