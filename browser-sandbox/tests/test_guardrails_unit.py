"""
Camada 1: testes unitarios puros da logica de guardrails, sem Playwright e
sem Docker. Toda a superficie testada aqui roda em memoria, com IPs e
strings sinteticas - nenhum destes testes faz uma requisicao de rede de
verdade. Isso os torna deterministicos e rapidos o suficiente pra rodar em
todo commit.
"""

import pytest

from guardrails.domain_allowlist import build_domain_allowlist
from guardrails.file_guard import DEFAULT_BLOCKED_EXTENSIONS, evaluate_download, sniff_executable
from guardrails.network_guard import is_blocked_ip, is_ip_literal
from guardrails.policy import BrowserSandboxPolicy, Decision
from guardrails.session_limits import SessionLimiter, SessionLimits


# ---------------------------------------------------------------------------
# domain_allowlist
# ---------------------------------------------------------------------------


def test_exact_domain_is_allowed():
    allowlist = build_domain_allowlist(["docs.python.org"])
    assert allowlist.is_allowed("docs.python.org")


def test_exact_domain_is_case_insensitive():
    allowlist = build_domain_allowlist(["Docs.Python.org"])
    assert allowlist.is_allowed("docs.python.org")


def test_exact_domain_does_not_match_subdomain_implicitly():
    allowlist = build_domain_allowlist(["python.org"])
    assert not allowlist.is_allowed("evil.python.org.attacker.com")
    assert not allowlist.is_allowed("sub.python.org")


def test_domain_outside_allowlist_is_blocked():
    allowlist = build_domain_allowlist(["docs.python.org"])
    assert not allowlist.is_allowed("attacker.example")


def test_regex_pattern_allows_any_subdomain():
    allowlist = build_domain_allowlist([r"^.*\.example\.com$"])
    assert allowlist.is_allowed("app.example.com")
    assert allowlist.is_allowed("a.b.example.com")
    assert not allowlist.is_allowed("example.com")  # o regex exige um subdominio
    assert not allowlist.is_allowed("notexample.com")


# ---------------------------------------------------------------------------
# network_guard (bloqueio de IP privado / SSRF)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.255.255",
        "169.254.0.1",
        "169.254.169.254",  # endereco classico de metadata de cloud (AWS/GCP/Azure)
        "127.0.0.1",
        "127.255.255.255",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_private_and_reserved_ips_are_blocked(ip):
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "142.250.190.14", "2606:4700:4700::1111"])
def test_public_ips_are_not_blocked(ip):
    assert is_blocked_ip(ip) is False


def test_invalid_ip_string_is_blocked_fail_closed():
    assert is_blocked_ip("nao-e-um-ip") is True
    assert is_blocked_ip("") is True


def test_is_ip_literal_distinguishes_ip_from_hostname():
    assert is_ip_literal("169.254.169.254") is True
    assert is_ip_literal("example.com") is False


# ---------------------------------------------------------------------------
# file_guard (extensao + magic bytes)
# ---------------------------------------------------------------------------


def test_benign_file_is_allowed():
    result = evaluate_download("relatorio.pdf", b"%PDF-1.4 conteudo qualquer")
    assert result.blocked is False


def test_file_blocked_by_extension():
    result = evaluate_download("instalador.exe", b"conteudo irrelevante")
    assert result.blocked is True
    assert "extensao" in result.reason.lower() or "extensão" in result.reason.lower()


def test_disguised_executable_blocked_by_magic_bytes_despite_safe_extension():
    """
    O caso central do requisito: um arquivo com nome de imagem (.jpg) mas
    conteudo de um executavel Windows (PE, assinatura 'MZ'). A extensao
    sozinha nao pegaria isso.
    """
    pe_header = b"MZ" + b"\x00" * 58 + b"PE\x00\x00resto do binario simulado"
    result = evaluate_download("foto_de_ferias.jpg", pe_header)
    assert result.blocked is True
    assert "pe_executable" in result.reason


def test_sniff_executable_detects_elf_and_shebang():
    assert sniff_executable(b"\x7fELF\x02\x01\x01\x00...") is not None
    assert sniff_executable(b"#!/bin/bash\nrm -rf /") is not None
    assert sniff_executable(b"conteudo de texto normal") is None


def test_default_blocked_extensions_cover_common_executables():
    for ext in (".exe", ".sh", ".dll", ".bat", ".apk"):
        assert ext in DEFAULT_BLOCKED_EXTENSIONS


# ---------------------------------------------------------------------------
# session_limits
# ---------------------------------------------------------------------------


def test_session_not_expired_within_limits():
    clock = {"t": 0.0}
    limiter = SessionLimiter(SessionLimits(max_pages=5, max_duration_seconds=100), now_fn=lambda: clock["t"])
    limiter.start()
    limiter.record_page_visit()
    limiter.record_page_visit()
    assert limiter.is_expired() is False


def test_session_expires_by_page_count():
    clock = {"t": 0.0}
    limiter = SessionLimiter(SessionLimits(max_pages=2, max_duration_seconds=1000), now_fn=lambda: clock["t"])
    limiter.start()
    limiter.record_page_visit()
    limiter.record_page_visit()
    limiter.record_page_visit()  # 3a pagina, limite e 2
    assert limiter.is_expired() is True
    assert "paginas" in limiter.expiry_reason()


def test_session_expires_by_elapsed_time():
    clock = {"t": 0.0}
    limiter = SessionLimiter(SessionLimits(max_pages=1000, max_duration_seconds=60), now_fn=lambda: clock["t"])
    limiter.start()
    clock["t"] = 61.0
    assert limiter.is_expired() is True
    assert "60" in limiter.expiry_reason() or "s por sessao" in limiter.expiry_reason()


# ---------------------------------------------------------------------------
# policy (composicao completa - equivalente ao CircuitBreaker)
# ---------------------------------------------------------------------------


def _fresh_policy(allowed=("docs.python.org",), max_pages=20, max_duration=300):
    allowlist = build_domain_allowlist(list(allowed))
    limiter = SessionLimiter(SessionLimits(max_pages=max_pages, max_duration_seconds=max_duration))
    limiter.start()
    return BrowserSandboxPolicy(allowlist, limiter)


def test_policy_approves_allowed_domain():
    policy = _fresh_policy()
    result = policy.evaluate_navigation("https://docs.python.org/3/library/ipaddress.html")
    assert result.decision == Decision.APPROVED


def test_policy_blocks_domain_outside_allowlist():
    policy = _fresh_policy()
    result = policy.evaluate_navigation("https://attacker.example/phish")
    assert result.decision == Decision.BLOCKED_DOMAIN


def test_policy_blocks_ssrf_to_cloud_metadata_even_if_no_domain_check_would_catch_it():
    """
    Cenario central de SSRF: o agente tenta navegar direto para o IP de
    metadata, sem passar por nenhum hostname. A checagem de IP roda ANTES
    da checagem de allowlist de dominio e bloqueia por si so.
    """
    policy = _fresh_policy()
    result = policy.evaluate_navigation("http://169.254.169.254/latest/meta-data/")
    assert result.decision == Decision.BLOCKED_SSRF


def test_policy_blocks_ip_literal_even_if_explicitly_in_allowlist():
    """
    Defesa em profundidade: mesmo que alguem configure a sessao com o IP
    de metadata explicitamente na allowlist (erro de configuracao, ou
    tentativa deliberada de burlar a checagem), o bloqueio de IP privado
    tem prioridade e vence de qualquer forma.
    """
    policy = _fresh_policy(allowed=("169.254.169.254",))
    result = policy.evaluate_navigation("http://169.254.169.254/")
    assert result.decision == Decision.BLOCKED_SSRF


def test_policy_blocks_when_session_expired():
    policy = _fresh_policy(max_pages=1)
    policy.session_limiter.record_page_visit()
    policy.session_limiter.record_page_visit()  # excede max_pages=1
    result = policy.evaluate_navigation("https://docs.python.org/")
    assert result.decision == Decision.BLOCKED_SESSION_EXPIRED


def test_policy_evaluate_download_blocks_disguised_executable():
    policy = _fresh_policy()
    pe_header = b"MZ" + b"\x00" * 58 + b"PE\x00\x00"
    result = policy.evaluate_download("fatura.pdf", pe_header)
    assert result.decision == Decision.BLOCKED_DOWNLOAD


def test_policy_evaluate_download_allows_benign_file():
    policy = _fresh_policy()
    result = policy.evaluate_download("fatura.pdf", b"%PDF-1.4 ...")
    assert result.decision == Decision.APPROVED


def test_policy_allows_file_scheme_bypassing_domain_and_ssrf_checks():
    """
    file:// nao passa pela allowlist de dominio nem pela checagem de IP -
    o risco que ele carrega (leitura de arquivo local) e contido pelo bind
    mount read-only do container, nao pelo guardrail de rede.
    """
    policy = _fresh_policy(allowed=())  # allowlist vazia - nenhum dominio permitido
    result = policy.evaluate_navigation("file:///workspace/trap.html")
    assert result.decision == Decision.APPROVED


def test_policy_allows_data_and_blob_schemes():
    policy = _fresh_policy(allowed=())
    assert policy.evaluate_navigation("data:text/plain;base64,aGVsbG8=").decision == Decision.APPROVED
    assert policy.evaluate_navigation("blob:https://example.com/uuid").decision == Decision.APPROVED
