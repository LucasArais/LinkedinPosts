"""
Servidor HTTP que roda DENTRO do container isolado. Possui o processo do
Playwright/Chromium e aplica a BrowserSandboxPolicy antes de qualquer
requisicao de rede (via `context.route("**/*", ...)`, nao so a navegacao de
topo - isso cobre XHR, imagens, scripts, iframes e redirects) e antes de
qualquer download.

E exposto como API HTTP de proposito: essa fronteira e a peca de isolamento
real do projeto. Um agente rodando no host, em outro container, ou em
qualquer framework (LangChain, Claude Agent SDK, o que for) nunca tem
acesso direto ao processo do browser nem ao filesystem do container alem do
que estes endpoints expoem deliberadamente - ele so fala HTTP.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request as flask_request
from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

from browser_sandbox.audit.logger import AuditLogger
from browser_sandbox.core.dns_guard import hostname_resolves_to_blocked_ip
from browser_sandbox.guardrails.domain_allowlist import build_domain_allowlist
from browser_sandbox.guardrails.network_guard import is_ip_literal
from browser_sandbox.guardrails.policy import BrowserSandboxPolicy, Decision, PolicyResult, extract_hostname
from browser_sandbox.guardrails.session_limits import SessionLimiter, SessionLimits

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser_sandbox")


class BrowserSandboxSession:
    def __init__(
        self,
        allowed_domains,
        max_pages: int,
        max_duration_seconds: float,
        downloads_dir: str,
        log_path: str,
        session_id: str,
    ):
        allowlist = build_domain_allowlist(allowed_domains)
        limiter = SessionLimiter(SessionLimits(max_pages=max_pages, max_duration_seconds=max_duration_seconds))
        limiter.start()
        self.policy = BrowserSandboxPolicy(allowlist, limiter)
        self.audit = AuditLogger(Path(log_path), session_id)
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.step = 0

        self._pw = sync_playwright().start()
        # Chromium roda sem acesso a variaveis de ambiente do host: o
        # processo Python deste servidor so recebe o que o `docker run`
        # explicitamente passar com `-e`; por padrao, nada.
        #
        # --disable-dev-shm-usage: o /dev/shm padrao de um container Docker
        # e minusculo (64MB) e insuficiente para o Chromium: o processo de
        # browser chega a iniciar, mas a renderizacao de pagina real crasha
        # (erro classico de "Chromium em Docker"). Essa flag manda o
        # Chromium usar /tmp em vez de /dev/shm, funcionando
        # independentemente do --shm-size configurado no host.
        self.browser: Browser = self._pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self.context: BrowserContext = self.browser.new_context(accept_downloads=True)
        self.context.route("**/*", self._route_handler)
        self.context.on("page", self._register_download_handler)
        self.pages = [self.context.new_page()]
        self._register_download_handler(self.pages[0])
        self.active_page_index = 0
        self._last_blocked_navigation: Optional[PolicyResult] = None

    # ------------------------------------------------------------------
    # Enforcamento na camada de rede
    # ------------------------------------------------------------------
    def _route_handler(self, route: Route) -> None:
        req = route.request
        url = req.url
        self.step += 1

        result: PolicyResult = self.policy.evaluate_navigation(url)
        if result.allowed:
            hostname = extract_hostname(url)
            if hostname and not is_ip_literal(hostname) and hostname_resolves_to_blocked_ip(hostname):
                result = PolicyResult(
                    Decision.BLOCKED_SSRF,
                    f"'{hostname}' resolve para um IP privado (possivel DNS rebinding)",
                )

        self.audit.log_decision(
            self.step, "network_request", {"url": url, "resource_type": req.resource_type},
            result.decision.value, result.reason,
        )

        if result.allowed:
            route.continue_()
        else:
            logger.warning("BLOQUEADO [%s]: %s (%s)", result.decision.value, url, result.reason)
            if req.resource_type == "document":
                # navegacao de topo (nao um subrecurso) - guarda a decisao
                # para que navigate() consiga reportar o bloqueio de forma
                # confiavel, sem depender de parsear a string de erro que o
                # Chromium devolve (varia entre versoes: ERR_ABORTED,
                # ERR_FAILED, etc).
                self._last_blocked_navigation = result
            route.abort()

    def _register_download_handler(self, page: Page) -> None:
        page.on("download", self._on_download)

    def _on_download(self, download) -> None:
        suggested = download.suggested_filename
        tmp_path = self.downloads_dir / f".tmp_{suggested}"
        download.save_as(str(tmp_path))
        content = tmp_path.read_bytes()

        self.step += 1
        result = self.policy.evaluate_download(suggested, content)
        self.audit.log_decision(self.step, "download", {"filename": suggested}, result.decision.value, result.reason)

        if result.allowed:
            tmp_path.rename(self.downloads_dir / suggested)
        else:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Acoes expostas como tools
    # ------------------------------------------------------------------
    @property
    def page(self) -> Page:
        return self.pages[self.active_page_index]

    def navigate(self, url: str) -> dict:
        self.step += 1
        if self.policy.session_limiter.is_expired():
            reason = self.policy.session_limiter.expiry_reason()
            self.audit.log_decision(self.step, "navigate", {"url": url}, "blocked_session_expired", reason)
            return {"ok": False, "blocked": True, "reason": reason}

        self.policy.session_limiter.record_page_visit()
        self.audit.log_action(self.step, "navigate", {"url": url})
        self._last_blocked_navigation = None
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self.audit.log_result(self.step, "navigate", {"final_url": self.page.url})
            return {"ok": True, "final_url": self.page.url}
        except Exception as exc:  # navegacao abortada pelo route handler cai aqui tambem
            blocked = self._last_blocked_navigation
            self.audit.log_result(self.step, "navigate", None, error=str(exc))
            if blocked is not None:
                return {
                    "ok": False,
                    "blocked": True,
                    "decision": blocked.decision.value,
                    "reason": blocked.reason,
                }
            return {"ok": False, "blocked": False, "error": str(exc)}

    def click(self, selector: str) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "click", {"selector": selector})
        try:
            self.page.click(selector, timeout=10000)
            self.audit.log_result(self.step, "click", {"clicked": selector})
            return {"ok": True}
        except Exception as exc:
            self.audit.log_result(self.step, "click", None, error=str(exc))
            return {"ok": False, "error": str(exc)}

    def type_text(self, selector: str, text: str) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "type", {"selector": selector, "text_length": len(text)})
        try:
            self.page.fill(selector, text, timeout=10000)
            self.audit.log_result(self.step, "type", {"filled": selector})
            return {"ok": True}
        except Exception as exc:
            self.audit.log_result(self.step, "type", None, error=str(exc))
            return {"ok": False, "error": str(exc)}

    def read_page(self) -> dict:
        self.step += 1
        text = self.page.inner_text("body") if self.page.query_selector("body") else ""
        result = {"url": self.page.url, "title": self.page.title(), "text": text[:20000]}
        self.audit.log_action(self.step, "read_page", {})
        self.audit.log_result(self.step, "read_page", {"url": result["url"], "text_length": len(text)})
        return result

    def screenshot(self) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "screenshot", {})
        img_bytes = self.page.screenshot(type="png")
        self.audit.log_result(self.step, "screenshot", {"bytes": len(img_bytes)})
        return {"image_base64": base64.b64encode(img_bytes).decode("ascii")}

    def go_back(self) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "go_back", {})
        self.page.go_back(timeout=10000)
        return {"ok": True, "url": self.page.url}

    def go_forward(self) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "go_forward", {})
        self.page.go_forward(timeout=10000)
        return {"ok": True, "url": self.page.url}

    def list_open_tabs(self) -> dict:
        return {"tabs": [{"index": i, "url": p.url} for i, p in enumerate(self.pages)], "active": self.active_page_index}

    def new_tab(self) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "new_tab", {})
        page = self.context.new_page()
        self._register_download_handler(page)
        self.pages.append(page)
        self.active_page_index = len(self.pages) - 1
        return {"ok": True, "index": self.active_page_index}

    def close_tab(self, index: int) -> dict:
        self.step += 1
        self.audit.log_action(self.step, "close_tab", {"index": index})
        if index < 0 or index >= len(self.pages):
            return {"ok": False, "error": "indice de aba invalido"}
        self.pages[index].close()
        del self.pages[index]
        if not self.pages:
            self.pages.append(self.context.new_page())
        self.active_page_index = min(self.active_page_index, len(self.pages) - 1)
        return {"ok": True}

    def close(self) -> None:
        self.audit.log_session_end(self.step, "closed", "Sessao encerrada")
        self.browser.close()
        self._pw.stop()


def create_app(session: BrowserSandboxSession) -> Flask:
    app = Flask(__name__)

    @app.post("/navigate")
    def navigate():
        return jsonify(session.navigate(flask_request.get_json()["url"]))

    @app.post("/click")
    def click():
        return jsonify(session.click(flask_request.get_json()["selector"]))

    @app.post("/type")
    def type_text():
        data = flask_request.get_json()
        return jsonify(session.type_text(data["selector"], data["text"]))

    @app.get("/read_page")
    def read_page():
        return jsonify(session.read_page())

    @app.get("/screenshot")
    def screenshot():
        return jsonify(session.screenshot())

    @app.post("/go_back")
    def go_back():
        return jsonify(session.go_back())

    @app.post("/go_forward")
    def go_forward():
        return jsonify(session.go_forward())

    @app.get("/tabs")
    def tabs():
        return jsonify(session.list_open_tabs())

    @app.post("/new_tab")
    def new_tab():
        return jsonify(session.new_tab())

    @app.post("/close_tab")
    def close_tab():
        return jsonify(session.close_tab(flask_request.get_json()["index"]))

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    return app


def main() -> None:
    allowed_domains = [d for d in os.environ.get("SANDBOX_ALLOWED_DOMAINS", "").split(",") if d]
    max_pages = int(os.environ.get("SANDBOX_MAX_PAGES", "20"))
    max_duration = float(os.environ.get("SANDBOX_MAX_DURATION_SECONDS", "300"))
    session_id = os.environ.get("SANDBOX_SESSION_ID", "default-session")

    session = BrowserSandboxSession(
        allowed_domains=allowed_domains,
        max_pages=max_pages,
        max_duration_seconds=max_duration,
        downloads_dir="/downloads",
        log_path="/logs/audit.jsonl",
        session_id=session_id,
    )
    app = create_app(session)
    app.run(host="0.0.0.0", port=8088, threaded=False)


if __name__ == "__main__":
    main()
