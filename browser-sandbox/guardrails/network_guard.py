"""
Bloqueio de IP privado/reservado - a defesa central contra SSRF.

Este modulo e deliberadamente burro e sem I/O: `is_blocked_ip` so avalia a
string de IP que recebe, sem resolver DNS. Isso o torna testavel com IPs
sinteticos em milissegundos (Camada 1). A parte que falta para uma defesa
SSRF completa - resolver o hostname e checar o IP resolvido antes de deixar
a requisicao sair, protegendo contra DNS rebinding - depende de I/O de rede
de verdade e vive em `core/`, testada na Camada 2 contra o browser real.

As duas camadas se complementam:
  - is_blocked_ip: pega URLs que ja contem um IP literal (o ataque mais
    simples: `http://169.254.169.254/...`);
  - a checagem pos-DNS em core/: pega dominios que resolvem para um IP
    privado (o ataque mais sofisticado).
"""

import ipaddress
from typing import Optional, Union

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# 169.254.0.0/16 ja cobre 169.254.169.254 (endereco classico de metadata de
# cloud em AWS/GCP/Azure), mas ele fica listado explicitamente no README e
# nos testes por ser o alvo mais comum de SSRF contra ambientes de nuvem.
RESERVED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # inclui 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 - pode expor IPv4 interno
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local (equivalente IPv6 do 169.254/16)
]


def parse_ip(value: str) -> Optional[IPAddress]:
    """Retorna o IP parseado, ou None se `value` nao for um literal de IP."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def is_blocked_ip(ip_str: str) -> bool:
    """
    True se o IP for privado/reservado (e portanto bloqueado), OU se a
    string nao for um IP valido - fail-closed: quem chama essa funcao ja
    decidiu que tinha um literal de IP em maos, entao uma string
    inesperada e tratada como suspeita, nao como "passa direto".
    """
    ip = parse_ip(ip_str)
    if ip is None:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip in network for network in RESERVED_NETWORKS)


def is_ip_literal(hostname: str) -> bool:
    """True se `hostname` e, ele mesmo, um literal de IP (v4 ou v6)."""
    return parse_ip(hostname) is not None
