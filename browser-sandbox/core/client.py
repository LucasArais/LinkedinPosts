"""
Cliente HTTP fino para falar com o BrowserSandboxSession rodando dentro do
container. Roda FORA do container (no host, em outro container, em
qualquer processo) e nao importa nada de `guardrails/` ou `core/` alem
deste arquivo - so faz requisicoes HTTP. E essa a peca que faz o projeto
ser plugavel em qualquer framework de agente: LangChain, Claude Agent SDK,
ou codigo cru, todos so precisam saber chamar estes metodos.
"""

from typing import Any, Dict

import requests


class BrowserSandboxClient:
    def __init__(self, base_url: str = "http://localhost:8088", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def navigate(self, url: str) -> Dict[str, Any]:
        return self._post("/navigate", {"url": url})

    def click(self, selector: str) -> Dict[str, Any]:
        return self._post("/click", {"selector": selector})

    def type(self, selector: str, text: str) -> Dict[str, Any]:
        return self._post("/type", {"selector": selector, "text": text})

    def read_page(self) -> Dict[str, Any]:
        return self._get("/read_page")

    def screenshot(self) -> Dict[str, Any]:
        return self._get("/screenshot")

    def go_back(self) -> Dict[str, Any]:
        return self._post("/go_back", {})

    def go_forward(self) -> Dict[str, Any]:
        return self._post("/go_forward", {})

    def list_open_tabs(self) -> Dict[str, Any]:
        return self._get("/tabs")

    def new_tab(self) -> Dict[str, Any]:
        return self._post("/new_tab", {})

    def close_tab(self, index: int) -> Dict[str, Any]:
        return self._post("/close_tab", {"index": index})

    def is_healthy(self) -> bool:
        try:
            return self._get("/healthz").get("ok", False)
        except requests.RequestException:
            return False
