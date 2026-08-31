"""
BrowserSandboxPolicy: compoe domain_allowlist + network_guard + file_guard +
session_limits num unico ponto de decisao, chamado antes de qualquer acao
real do browser (navegar, baixar arquivo). Equivalente, neste projeto, ao
CircuitBreaker do guarded-agent.

Ordem de avaliacao para navegacao (a primeira que bloquear, vence):
  1. sessao expirada (tempo ou numero de paginas)?
  2. o host do alvo e um literal de IP privado/reservado? -> bloqueia
     SEMPRE, mesmo que esse literal esteja, por engano, na allowlist de
     dominio. IP privado nunca e um destino de navegacao legitimo para um
     agente que fala com a internet publica.
  3. o host esta na allowlist de dominios da sessao?
  4. aprovado (a checagem de IP pos-DNS - contra dominios que resolvem
     para um IP privado - acontece em core/, ja que exige uma resolucao de
     DNS de verdade e nao e pura o suficiente para a Camada 1).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit

from .domain_allowlist import DomainAllowlist
from .file_guard import FileGuardResult, evaluate_download
from .network_guard import is_blocked_ip, is_ip_literal
from .session_limits import SessionLimiter


class Decision(str, Enum):
    APPROVED = "approved"
    BLOCKED_SESSION_EXPIRED = "blocked_session_expired"
    BLOCKED_SSRF = "blocked_ssrf"
    BLOCKED_DOMAIN = "blocked_domain"
    BLOCKED_DOWNLOAD = "blocked_download"
    BLOCKED_INVALID_URL = "blocked_invalid_url"


@dataclass
class PolicyResult:
    decision: Decision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.APPROVED


class BrowserSandboxPolicy:
    def __init__(self, domain_allowlist: DomainAllowlist, session_limiter: SessionLimiter):
        self.domain_allowlist = domain_allowlist
        self.session_limiter = session_limiter

    def evaluate_navigation(self, url: str) -> PolicyResult:
        if self.session_limiter.is_expired():
            return PolicyResult(Decision.BLOCKED_SESSION_EXPIRED, self.session_limiter.expiry_reason())

        if url.startswith(("file://", "data:", "blob:", "about:")):
            # Esquemas sem host remoto de verdade - nao ha dominio ou IP
            # para checar, entao a allowlist/SSRF nao se aplicam. file:// e
            # limitado pelo bind mount read-only do container; data:/blob:
            # sao conteudo inline, resolvidos localmente pelo proprio
            # browser, sem round-trip de rede. Ver limitacoes no README.
            return PolicyResult(Decision.APPROVED, f"Esquema '{url.split(':', 1)[0]}:' - fora do escopo do guardrail de rede")

        hostname = extract_hostname(url)
        if hostname is None:
            return PolicyResult(Decision.BLOCKED_INVALID_URL, f"Nao foi possivel extrair um host de '{url}'")

        if is_ip_literal(hostname) and is_blocked_ip(hostname):
            return PolicyResult(
                Decision.BLOCKED_SSRF,
                f"'{hostname}' e um IP privado/reservado - bloqueado independente da allowlist de dominio",
            )

        if not self.domain_allowlist.is_allowed(hostname):
            return PolicyResult(
                Decision.BLOCKED_DOMAIN, f"Dominio '{hostname}' nao esta na allowlist da sessao"
            )

        return PolicyResult(Decision.APPROVED, "Dominio permitido, sessao dentro dos limites")

    def evaluate_download(self, filename: str, content: bytes) -> PolicyResult:
        result: FileGuardResult = evaluate_download(filename, content)
        if result.blocked:
            return PolicyResult(Decision.BLOCKED_DOWNLOAD, result.reason)
        return PolicyResult(Decision.APPROVED, result.reason)


def extract_hostname(url: str) -> Optional[str]:
    parsed = urlsplit(url if "://" in url else f"http://{url}")
    return parsed.hostname
