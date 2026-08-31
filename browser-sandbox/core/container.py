"""
Lifecycle programatico do container do browser sandbox: builda a imagem se
preciso, sobe com as mesmas flags de isolamento de `docker/run.sh`, espera
ficar saudavel via `/healthz`, e derruba. Usado pelos testes de integracao
(Camada 2) e pelo modo de demonstracao - ambos precisam controlar o
container a partir de Python, nao so da linha de comando.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_NAME = "browser-sandbox:latest"


class ContainerStartupError(RuntimeError):
    pass


@dataclass
class ContainerHandle:
    name: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"

    def stop(self) -> None:
        subprocess.run(["docker", "stop", self.name], capture_output=True, timeout=30)


def docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def image_exists(image: str = IMAGE_NAME) -> bool:
    result = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    return result.returncode == 0


def build_image(image: str = IMAGE_NAME) -> None:
    subprocess.run(
        ["docker", "build", "-t", image, "-f", "docker/Dockerfile", "."],
        cwd=PROJECT_ROOT,
        check=True,
    )


def start_container(
    allowed_domains: List[str],
    max_pages: int = 20,
    max_duration_seconds: float = 300,
    name: str = "browser-sandbox-test",
    port: int = 8089,
    wait_healthy_timeout: float = 30.0,
) -> ContainerHandle:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    workspace = PROJECT_ROOT / "workspace"
    downloads = PROJECT_ROOT / "downloads"
    logs = PROJECT_ROOT / "logs"
    for d in (workspace, downloads, logs):
        d.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-p", f"{port}:8088",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=256m",
            "-v", f"{workspace}:/workspace:ro",
            "-v", f"{downloads}:/downloads:rw",
            "-v", f"{logs}:/logs:rw",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true",
            "--memory=1g", "--cpus=1",
            "-e", f"SANDBOX_ALLOWED_DOMAINS={','.join(allowed_domains)}",
            "-e", f"SANDBOX_MAX_PAGES={max_pages}",
            "-e", f"SANDBOX_MAX_DURATION_SECONDS={max_duration_seconds}",
            "-e", f"SANDBOX_SESSION_ID={name}",
            IMAGE_NAME,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ContainerStartupError(f"docker run falhou: {result.stderr}")

    handle = ContainerHandle(name=name, port=port)
    deadline = time.monotonic() + wait_healthy_timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{handle.base_url}/healthz", timeout=1).ok:
                return handle
        except requests.RequestException:
            pass
        time.sleep(0.5)
    handle.stop()
    raise ContainerStartupError(f"Container '{name}' nao ficou saudavel em {wait_healthy_timeout}s")
