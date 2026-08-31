"""
Guardrail de download: bloqueia arquivos executaveis por extensao E por
magic bytes. As duas checagens sao independentes e o bloqueio vale se
QUALQUER uma disparar - isso e o que pega o caso de um `relatorio.jpg` que
na verdade e um binario PE, disfarcado so trocando a extensao do nome.
"""

from dataclasses import dataclass
from typing import FrozenSet, Optional

DEFAULT_BLOCKED_EXTENSIONS: FrozenSet[str] = frozenset(
    {
        ".exe", ".dll", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".vbe",
        ".scr", ".com", ".jar", ".app", ".dmg", ".pkg", ".sh", ".bash",
        ".zsh", ".command", ".apk", ".deb", ".rpm",
    }
)

# Assinaturas de magic bytes de formatos executaveis/scripts nos principais
# SOs. Nao e uma lista exaustiva de todo binario possivel - e o suficiente
# para pegar o caso de uso realista (agente engana o download disfarcando a
# extensao de um executavel comum).
_EXECUTABLE_SIGNATURES = (
    (b"MZ", "pe_executable (Windows .exe/.dll)"),
    (b"\x7fELF", "elf_executable (Linux)"),
    (b"\xfe\xed\xfa\xce", "macho_32 (macOS)"),
    (b"\xfe\xed\xfa\xcf", "macho_64 (macOS)"),
    (b"\xce\xfa\xed\xfe", "macho_32_reverse (macOS)"),
    (b"\xcf\xfa\xed\xfe", "macho_64_reverse (macOS)"),
    (b"\xca\xfe\xba\xbe", "macho_universal_binary (macOS fat binary)"),
    (b"#!/bin/sh", "shebang_script"),
    (b"#!/bin/bash", "shebang_script"),
    (b"#!/usr/bin/env", "shebang_script"),
    (b"#!/bin/zsh", "shebang_script"),
)


def sniff_executable(content: bytes) -> Optional[str]:
    """Retorna a descricao da assinatura encontrada, ou None se nao bater com nenhuma."""
    for signature, description in _EXECUTABLE_SIGNATURES:
        if content.startswith(signature):
            return description
    return None


@dataclass
class FileGuardResult:
    blocked: bool
    reason: str


def evaluate_download(
    filename: str,
    content: bytes,
    blocked_extensions: FrozenSet[str] = DEFAULT_BLOCKED_EXTENSIONS,
) -> FileGuardResult:
    suffix = _extension_of(filename)
    if suffix in blocked_extensions:
        return FileGuardResult(
            blocked=True, reason=f"Extensao '{suffix}' esta na lista de extensoes bloqueadas"
        )

    signature = sniff_executable(content)
    if signature is not None:
        return FileGuardResult(
            blocked=True,
            reason=f"Conteudo do arquivo bate com assinatura de executavel ({signature}), "
            f"independente da extensao '{suffix or '(nenhuma)'}'",
        )

    return FileGuardResult(blocked=False, reason="Extensao e magic bytes OK")


def _extension_of(filename: str) -> str:
    name = filename.strip().lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[1]
