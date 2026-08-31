"""
Camada 4: teste leve de carga/abuso. Abre varias abas, navega
repetidamente, e mede uso de CPU/memoria do container via `docker stats`
para confirmar que nao ha vazamento de recurso nem crash do host durante
uso intenso. Nao e um benchmark de performance - e um smoke test de que o
container aguenta uso continuo sem morrer nem estourar os limites de
`--memory`/`--cpus` definidos em docker/run.sh.

Requer Docker rodando. Roda separado da suite principal por ser mais lento
(bate contra o dominio de exemplo repetidas vezes):

    pytest tests/test_load.py -v -s
"""

import subprocess
import time
from pathlib import Path

import pytest
import requests

from core.container import docker_available, image_exists, build_image, start_container

PROJECT_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker nao esta disponivel/rodando neste ambiente"
)

TABS = 4
NAVIGATIONS_PER_TAB = 5
MEMORY_LIMIT_MB = 1024  # deve bater com --memory=1g em docker/run.sh e core/container.py


@pytest.fixture(scope="module", autouse=True)
def ensure_image_built():
    if not image_exists():
        build_image()


def _docker_stats(container_name: str) -> dict:
    result = subprocess.run(
        ["docker", "stats", container_name, "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}"],
        capture_output=True, text=True, timeout=10,
    )
    cpu_str, mem_str = result.stdout.strip().split("|")
    mem_used_str = mem_str.split("/")[0].strip()  # ex: "312.4MiB"
    return {"cpu_percent": float(cpu_str.replace("%", "")), "mem_used_raw": mem_used_str}


def _mem_str_to_mb(mem_str: str) -> float:
    value = float("".join(c for c in mem_str if c.isdigit() or c == "."))
    if "GiB" in mem_str or "GB" in mem_str:
        return value * 1024
    return value  # assume MiB/MB


def test_container_survives_sustained_multi_tab_navigation():
    handle = start_container(
        allowed_domains=["docs.python.org", "example.com"],
        max_pages=TABS * NAVIGATIONS_PER_TAB + TABS + 5,
        name="browser-sandbox-test-load",
        port=8096,
    )
    samples = []
    urls = ["https://docs.python.org/3/", "https://example.com/", "https://docs.python.org/3/library/"]

    try:
        tab_indices = [0]
        for _ in range(TABS - 1):
            resp = requests.post(f"{handle.base_url}/new_tab", json={}, timeout=15).json()
            tab_indices.append(resp["index"])

        for round_num in range(NAVIGATIONS_PER_TAB):
            for url in urls:
                requests.post(f"{handle.base_url}/navigate", json={"url": url}, timeout=15)

            try:
                samples.append(_docker_stats(handle.name))
            except Exception:
                pass  # docker stats e best-effort, nao deve derrubar o teste

            resp = requests.get(f"{handle.base_url}/healthz", timeout=5)
            assert resp.ok, f"container parou de responder na rodada {round_num}"

        final_health = requests.get(f"{handle.base_url}/healthz", timeout=5)
        assert final_health.ok

    finally:
        handle.stop()

    assert samples, "nao foi possivel coletar nenhuma amostra de docker stats"
    max_mem_mb = max(_mem_str_to_mb(s["mem_used_raw"]) for s in samples)
    print(f"\n[Camada 4] amostras coletadas: {len(samples)}")
    print(f"[Camada 4] pico de memoria observado: {max_mem_mb:.1f} MiB (limite: {MEMORY_LIMIT_MB} MiB)")
    for i, s in enumerate(samples):
        print(f"  rodada {i}: cpu={s['cpu_percent']}% mem={s['mem_used_raw']}")

    assert max_mem_mb < MEMORY_LIMIT_MB, (
        f"uso de memoria ({max_mem_mb:.1f}MiB) chegou perto ou passou do limite do container ({MEMORY_LIMIT_MB}MiB)"
    )
