"""
Wrapper das acoes do BrowserSandboxClient no formato tool_use da Anthropic
API. Isso e o que um agente de verdade (ou o loop de demo da Camada 3) usa
para falar com o browser sandboxed - o agente nunca importa `core/` nem
`guardrails/` diretamente, so ve estas sete ferramentas.

Para adaptar a outro framework (LangChain, Claude Agent SDK, funcao
generica de tool-calling, etc): a unica coisa que muda e o formato do
schema de cada ferramenta (o "shape" do JSON schema e praticamente
universal - `input_schema` vira `parameters` no formato OpenAI-style de
function calling, por exemplo). A LOGICA de execucao (dispatch_tool_call)
nao muda nada, porque ela so fala com o BrowserSandboxClient via HTTP -
funciona identico non importa quem esta chamando.
"""

from typing import Any, Dict

from core.client import BrowserSandboxClient

BROWSER_TOOL_SCHEMAS = [
    {
        "name": "navigate",
        "description": "Navega o browser sandboxed para uma URL. Bloqueado se o dominio nao estiver na allowlist da sessao ou for um IP privado/reservado.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Clica em um elemento da pagina atual, identificado por um seletor CSS.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "Seletor CSS do elemento"}},
            "required": ["selector"],
        },
    },
    {
        "name": "type",
        "description": "Preenche um campo de input/textarea com texto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "read_page",
        "description": "Retorna o texto e a URL da pagina atual (nao o HTML bruto).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": "Tira um screenshot da pagina atual (imagem PNG em base64).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "go_back",
        "description": "Volta para a pagina anterior no historico da aba atual.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "go_forward",
        "description": "Avanca para a proxima pagina no historico da aba atual.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_open_tabs",
        "description": "Lista as abas abertas na sessao e qual esta ativa.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "new_tab",
        "description": "Abre uma nova aba e a torna a aba ativa.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "close_tab",
        "description": "Fecha uma aba pelo indice.",
        "input_schema": {
            "type": "object",
            "properties": {"index": {"type": "integer"}},
            "required": ["index"],
        },
    },
]


def dispatch_tool_call(client: BrowserSandboxClient, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "navigate":
        return client.navigate(tool_input["url"])
    if tool_name == "click":
        return client.click(tool_input["selector"])
    if tool_name == "type":
        return client.type(tool_input["selector"], tool_input["text"])
    if tool_name == "read_page":
        return client.read_page()
    if tool_name == "screenshot":
        return client.screenshot()
    if tool_name == "go_back":
        return client.go_back()
    if tool_name == "go_forward":
        return client.go_forward()
    if tool_name == "list_open_tabs":
        return client.list_open_tabs()
    if tool_name == "new_tab":
        return client.new_tab()
    if tool_name == "close_tab":
        return client.close_tab(tool_input["index"])
    raise ValueError(f"Ferramenta desconhecida: {tool_name}")
