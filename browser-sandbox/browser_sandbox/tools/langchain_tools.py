"""
Adapter oficial para LangChain. Converte as mesmas 10 acoes de
`anthropic_tools.py` em `StructuredTool`s do langchain-core, prontas para
passar direto para `create_react_agent`, um `AgentExecutor`, ou qualquer
outro consumidor de `BaseTool` do LangChain.

A logica de execucao e identica ao adapter da Anthropic - so fala HTTP com
o `BrowserSandboxClient`. Isso e o ponto central do projeto: nenhum
framework precisa de um sandbox proprio, todos apontam para o mesmo
container.

Uso:

    from browser_sandbox.core.client import BrowserSandboxClient
    from browser_sandbox.tools.langchain_tools import get_browser_sandbox_tools

    client = BrowserSandboxClient(base_url="http://localhost:8088")
    tools = get_browser_sandbox_tools(client)

    # tools e uma List[StructuredTool] - passe direto para o seu agente:
    from langchain.agents import create_react_agent
    agent = create_react_agent(llm, tools, prompt)

Requer o extra opcional `langchain`: `pip install "browser-sandbox[langchain]"`.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

try:
    from langchain_core.tools import StructuredTool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "langchain_tools requer o extra 'langchain': pip install \"browser-sandbox[langchain]\""
    ) from exc

from browser_sandbox.core.client import BrowserSandboxClient


class NavigateInput(BaseModel):
    url: str = Field(description="URL para navegar. Bloqueado se o dominio nao estiver na allowlist da sessao ou for um IP privado/reservado.")


class ClickInput(BaseModel):
    selector: str = Field(description="Seletor CSS do elemento a clicar")


class TypeInput(BaseModel):
    selector: str = Field(description="Seletor CSS do campo")
    text: str = Field(description="Texto a digitar no campo")


class CloseTabInput(BaseModel):
    index: int = Field(description="Indice da aba a fechar")


class _NoInput(BaseModel):
    pass


def get_browser_sandbox_tools(client: BrowserSandboxClient) -> List["StructuredTool"]:
    """Retorna as 10 ferramentas do browser sandbox como StructuredTool do LangChain, ligadas a `client`."""

    return [
        StructuredTool.from_function(
            name="navigate",
            description="Navega o browser sandboxed para uma URL.",
            args_schema=NavigateInput,
            func=lambda url: client.navigate(url),
        ),
        StructuredTool.from_function(
            name="click",
            description="Clica em um elemento da pagina atual, identificado por um seletor CSS.",
            args_schema=ClickInput,
            func=lambda selector: client.click(selector),
        ),
        StructuredTool.from_function(
            name="type",
            description="Preenche um campo de input/textarea com texto.",
            args_schema=TypeInput,
            func=lambda selector, text: client.type(selector, text),
        ),
        StructuredTool.from_function(
            name="read_page",
            description="Retorna o texto e a URL da pagina atual (nao o HTML bruto).",
            args_schema=_NoInput,
            func=lambda: client.read_page(),
        ),
        StructuredTool.from_function(
            name="screenshot",
            description="Tira um screenshot da pagina atual (imagem PNG em base64).",
            args_schema=_NoInput,
            func=lambda: client.screenshot(),
        ),
        StructuredTool.from_function(
            name="go_back",
            description="Volta para a pagina anterior no historico da aba atual.",
            args_schema=_NoInput,
            func=lambda: client.go_back(),
        ),
        StructuredTool.from_function(
            name="go_forward",
            description="Avanca para a proxima pagina no historico da aba atual.",
            args_schema=_NoInput,
            func=lambda: client.go_forward(),
        ),
        StructuredTool.from_function(
            name="list_open_tabs",
            description="Lista as abas abertas na sessao e qual esta ativa.",
            args_schema=_NoInput,
            func=lambda: client.list_open_tabs(),
        ),
        StructuredTool.from_function(
            name="new_tab",
            description="Abre uma nova aba e a torna a aba ativa.",
            args_schema=_NoInput,
            func=lambda: client.new_tab(),
        ),
        StructuredTool.from_function(
            name="close_tab",
            description="Fecha uma aba pelo indice.",
            args_schema=CloseTabInput,
            func=lambda index: client.close_tab(index),
        ),
    ]
