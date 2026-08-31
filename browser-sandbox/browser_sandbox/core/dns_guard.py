"""
Checagem de SSRF pos-DNS: protege contra dominios que resolvem para um IP
privado (DNS rebinding), o que `guardrails/network_guard.py` sozinho nao
pega (aquele modulo so olha literais de IP, sem fazer I/O). Isso exige uma
resolucao de DNS de verdade, entao vive em `core/` e e exercitado pela
Camada 2 (testes de integracao), nao pela Camada 1.
"""

import socket
from typing import List

from browser_sandbox.guardrails.network_guard import is_blocked_ip


def resolve_ips(hostname: str) -> List[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def hostname_resolves_to_blocked_ip(hostname: str) -> bool:
    """Fail-closed: se a resolucao de DNS falhar, trata como bloqueado."""
    ips = resolve_ips(hostname)
    if not ips:
        return True
    return any(is_blocked_ip(ip) for ip in ips)
