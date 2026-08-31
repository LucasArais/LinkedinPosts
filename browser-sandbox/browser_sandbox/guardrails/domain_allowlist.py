"""
Allowlist de dominios por sessao. Cada entrada de configuracao pode ser:

- um hostname exato ("example.com") - comparado case-insensitive, sem
  match automatico de subdominio (explicito e mais seguro que implicito:
  se "app.example.com" tambem deve ser permitido, declare os dois);
- um padrao regex, se a entrada contiver qualquer metacaractere de regex
  (`* + ? ( ) [ ] { } ^ $ \\ |`) - comparado com re.fullmatch contra o
  hostname inteiro.

Isso separa dois casos de uso sem exigir uma sintaxe de prefixo especial:
"docs.python.org" e uma allowlist de um site so; r"^.*\\.example\\.com$" e
uma allowlist de qualquer subdominio de example.com.
"""

import re
from dataclasses import dataclass, field
from typing import FrozenSet, Sequence, Tuple

_REGEX_METACHARACTERS = set("*+?()[]{}^$\\|")


def _looks_like_regex(entry: str) -> bool:
    return any(ch in _REGEX_METACHARACTERS for ch in entry)


@dataclass(frozen=True)
class DomainAllowlist:
    exact_domains: FrozenSet[str] = field(default_factory=frozenset)
    patterns: Tuple["re.Pattern[str]", ...] = field(default_factory=tuple)

    def is_allowed(self, hostname: str) -> bool:
        normalized = hostname.strip().lower().rstrip(".")
        if not normalized:
            return False
        if normalized in self.exact_domains:
            return True
        return any(p.fullmatch(normalized) for p in self.patterns)


def build_domain_allowlist(entries: Sequence[str]) -> DomainAllowlist:
    exact = set()
    patterns = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if _looks_like_regex(entry):
            patterns.append(re.compile(entry, re.IGNORECASE))
        else:
            exact.add(entry.lower().rstrip("."))
    return DomainAllowlist(exact_domains=frozenset(exact), patterns=tuple(patterns))
