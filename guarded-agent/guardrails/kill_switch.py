"""
Kill switch: interrompe qualquer execucao em andamento, imediatamente,
por dois canais independentes (variavel de ambiente ou arquivo em disco).

Dois canais existem de proposito: a env var e rapida de setar de dentro do
mesmo shell que iniciou o agente; o arquivo permite que outro processo (ou
voce, em outro terminal, ou um watchdog externo) aborte uma sessao em
andamento sem precisar ter acesso ao ambiente do processo original.
"""

import os
from pathlib import Path

KILL_SWITCH_ENV_VAR = "AGENT_KILL_SWITCH"
KILL_SWITCH_FILE = Path(__file__).resolve().parent.parent / "KILL_SWITCH"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_kill_switch_active() -> bool:
    if os.environ.get(KILL_SWITCH_ENV_VAR, "").strip().lower() in _TRUE_VALUES:
        return True
    if KILL_SWITCH_FILE.exists():
        return True
    return False
