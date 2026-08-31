"""
Schemas de tool use no formato esperado pela Anthropic API.

Nota de design: o modelo recebe o TOOL_SCHEMAS completo (todas as
ferramentas existem para ele, mesmo as que a tarefa atual nao permite).
Isso e intencional - o objetivo do projeto e mostrar guardrails que nao
dependem do modelo "se comportar" ou do system prompt ser obedecido. A
restricao de verdade acontece na CircuitBreaker, fora do LLM, que e
justamente o tipo de camada que faltou nos incidentes de agentes que
escaparam do escopo pretendido por quem os configurou.
"""

TOOL_SCHEMAS = [
    {
        "name": "list_directory",
        "description": "Lista arquivos e subdiretorios de um caminho, com nome, tamanho e data de modificacao.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Caminho do diretorio"}},
            "required": ["path"],
        },
    },
    {
        "name": "make_directory",
        "description": "Cria um diretorio (e diretorios pais, se necessario) caso ele nao exista.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "move_file",
        "description": "Move ou renomeia um arquivo de 'source' para 'destination'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "read_file",
        "description": "Le o conteudo completo de um arquivo de texto.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Escreve (sobrescrevendo) conteudo em um arquivo de texto.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_shell",
        "description": "Executa um comando de shell no sistema. Sujeito a allowlist rigida por tarefa.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "http_request",
        "description": "Faz uma requisicao HTTP a uma URL e retorna status e corpo da resposta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
            },
            "required": ["url"],
        },
    },
]
