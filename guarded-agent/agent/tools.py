"""
Implementacao real das ferramentas. Este modulo NAO sabe nada sobre
guardrails - qualquer funcao aqui, se chamada, executa de verdade. Toda a
decisao de "pode ou nao pode chamar isso agora" acontece antes, na
CircuitBreaker. Deliberadamente burro: se o registry chamar a funcao, ela
roda.
"""

import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict


class ToolError(Exception):
    pass


def list_directory(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ToolError(f"'{path}' nao e um diretorio existente")
    entries = []
    for child in sorted(p.iterdir()):
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size_bytes": stat.st_size,
                "modified_epoch": stat.st_mtime,
            }
        )
    return {"path": str(p), "entries": entries}


def make_directory(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return {"created": str(p)}


def move_file(source: str, destination: str) -> Dict[str, Any]:
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    if not src.is_file():
        raise ToolError(f"Arquivo de origem nao existe: {source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"moved_from": str(src), "moved_to": str(dst)}


def read_file(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"Arquivo nao existe: {path}")
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")}


def write_file(path: str, content: str) -> Dict[str, Any]:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p), "bytes": len(content.encode("utf-8"))}


def run_shell(command: str) -> Dict[str, Any]:
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def http_request(url: str, method: str = "GET") -> Dict[str, Any]:
    req = urllib.request.Request(url, method=method.upper())
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read(4000).decode("utf-8", errors="replace")
        return {"url": url, "status": resp.status, "body": body}


TOOL_REGISTRY = {
    "list_directory": list_directory,
    "make_directory": make_directory,
    "move_file": move_file,
    "read_file": read_file,
    "write_file": write_file,
    "run_shell": run_shell,
    "http_request": http_request,
}
