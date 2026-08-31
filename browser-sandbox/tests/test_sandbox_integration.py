"""
Camada 2: testes de integracao contra o container real (Docker + Playwright
+ Chromium de verdade), sem nenhum agente/LLM envolvido - so chamadas HTTP
diretas para o BrowserSandboxSession, exercitando o mesmo caminho de codigo
que um agente usaria.

Requer Docker rodando localmente. O modulo inteiro e pulado (nao falha) se
o Docker nao estiver disponivel, para nao quebrar quem rodar `pytest tests/`
sem Docker instalado - rode explicitamente para validar a Camada 2:

    pytest tests/test_sandbox_integration.py -v

Cada teste sobe seu proprio container (via core.container) com a allowlist
minima necessaria para aquele cenario, e derruba no final.
"""

import http.server
import json
import socketserver
import threading
from pathlib import Path

import pytest
import requests

from browser_sandbox.core.container import ContainerHandle, build_image, docker_available, image_exists, start_container

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker nao esta disponivel/rodando neste ambiente"
)


@pytest.fixture(scope="module", autouse=True)
def ensure_image_built():
    if not image_exists():
        build_image()


def _clear_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for f in d.iterdir():
        if f.is_file():
            f.unlink()


@pytest.fixture
def workspace_dir():
    ws = PROJECT_ROOT / "workspace"
    _clear_dir(ws)  # limpa resíduo de runs manuais/anteriores antes de comecar
    yield ws
    _clear_dir(ws)


@pytest.fixture
def downloads_dir():
    d = PROJECT_ROOT / "downloads"
    _clear_dir(d)
    yield d
    _clear_dir(d)


@pytest.fixture
def audit_log_path():
    log_path = PROJECT_ROOT / "logs" / "audit.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()
    yield log_path


def _read_audit_decisions(log_path: Path):
    if not log_path.exists():
        return []
    decisions = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("type") == "decision":
            decisions.append(record)
    return decisions


# ---------------------------------------------------------------------------
# Cenario 1: navegacao para dominio fora da allowlist e bloqueada ANTES da
# requisicao sair - confirmado por um servidor local que nunca recebe nada.
# ---------------------------------------------------------------------------


def test_navigation_outside_allowlist_never_reaches_the_target(audit_log_path):
    hits = []

    class _RecordingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), _RecordingHandler) as httpd:
        mock_port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        handle = start_container(
            allowed_domains=["docs.python.org"],  # NAO inclui o host do mock
            name="browser-sandbox-test-domain",
            port=8090,
        )
        try:
            resp = requests.post(
                f"{handle.base_url}/navigate",
                json={"url": f"http://host.docker.internal:{mock_port}/secreto"},
                timeout=15,
            ).json()
            assert resp["ok"] is False
            assert resp["blocked"] is True
            assert resp["decision"] in ("blocked_domain", "blocked_ssrf")
        finally:
            handle.stop()
            httpd.shutdown()

    assert hits == [], f"O mock recebeu requisicoes que nunca deveriam ter saido do container: {hits}"

    decisions = _read_audit_decisions(audit_log_path)
    assert any(d["decision"] in ("blocked_domain", "blocked_ssrf") for d in decisions)


# ---------------------------------------------------------------------------
# Cenario 2: SSRF contra o endereco de metadata de cloud e qualquer range
# de IP privado e bloqueado.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://127.0.0.1:8088/",
    ],
)
def test_ssrf_targets_are_blocked(target_url, audit_log_path):
    handle = start_container(
        allowed_domains=["docs.python.org"], name="browser-sandbox-test-ssrf", port=8091
    )
    try:
        resp = requests.post(f"{handle.base_url}/navigate", json={"url": target_url}, timeout=15).json()
        assert resp["ok"] is False
        assert resp["blocked"] is True
        assert resp["decision"] == "blocked_ssrf"
    finally:
        handle.stop()


# ---------------------------------------------------------------------------
# Cenario 3: download disfarcado (extensao .jpg, conteudo de executavel PE)
# e rejeitado pelo magic-byte guard; um download benigno passa normalmente.
# ---------------------------------------------------------------------------


def test_disguised_executable_download_is_rejected(workspace_dir, downloads_dir, audit_log_path):
    fixture = FIXTURES_DIR / "disguised_download.html"
    (workspace_dir / "disguised_download.html").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    handle = start_container(allowed_domains=[], name="browser-sandbox-test-dl-bad", port=8092)
    try:
        nav = requests.post(
            f"{handle.base_url}/navigate",
            json={"url": "file:///workspace/disguised_download.html"},
            timeout=15,
        ).json()
        assert nav["ok"] is True

        click = requests.post(f"{handle.base_url}/click", json={"selector": "#dl"}, timeout=15).json()
        assert click["ok"] is True

        # pumpeia o event loop do playwright (o evento de download e
        # processado de forma assincrona pelo lado do servidor)
        requests.get(f"{handle.base_url}/read_page", timeout=15)
    finally:
        handle.stop()

    assert list(downloads_dir.iterdir()) == [], "o arquivo disfarcado nao deveria ter sido salvo"

    decisions = _read_audit_decisions(audit_log_path)
    download_decisions = [d for d in decisions if d.get("action") == "download"]
    assert len(download_decisions) == 1
    assert download_decisions[0]["decision"] == "blocked_download"
    assert "pe_executable" in download_decisions[0]["reason"]


def test_benign_download_is_accepted(workspace_dir, downloads_dir, audit_log_path):
    fixture = FIXTURES_DIR / "benign_download.html"
    (workspace_dir / "benign_download.html").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    handle = start_container(allowed_domains=[], name="browser-sandbox-test-dl-ok", port=8093)
    try:
        requests.post(
            f"{handle.base_url}/navigate", json={"url": "file:///workspace/benign_download.html"}, timeout=15
        )
        requests.post(f"{handle.base_url}/click", json={"selector": "#dl"}, timeout=15)
        requests.get(f"{handle.base_url}/read_page", timeout=15)
    finally:
        handle.stop()

    downloaded = list(downloads_dir.iterdir())
    assert len(downloaded) == 1
    assert downloaded[0].name == "relatorio.pdf"


# ---------------------------------------------------------------------------
# Cenario 4: a sessao se encerra sozinha ao exceder o limite de paginas.
# ---------------------------------------------------------------------------


def test_session_auto_expires_after_page_limit(audit_log_path):
    handle = start_container(
        allowed_domains=["docs.python.org", "example.com"],
        max_pages=2,
        name="browser-sandbox-test-limit",
        port=8094,
    )
    try:
        r1 = requests.post(f"{handle.base_url}/navigate", json={"url": "https://docs.python.org/3/"}, timeout=15).json()
        r2 = requests.post(f"{handle.base_url}/navigate", json={"url": "https://example.com/"}, timeout=15).json()
        r3 = requests.post(
            f"{handle.base_url}/navigate", json={"url": "https://docs.python.org/3/library/"}, timeout=15
        ).json()
    finally:
        handle.stop()

    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r3["ok"] is False
    assert r3["decision"] == "blocked_session_expired"
    assert "2" in r3["reason"]
