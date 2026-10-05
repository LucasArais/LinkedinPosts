"""
CLI interativa do scoped-memory: um unico loop de terminal, um unico
agente, varios usuarios.

Uso:
    python main.py
    python main.py --db outro.db

Comandos: /user <nome>, /team <nome>, /whoami, /memories, /help, /quit.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from scoped_memory import display
from scoped_memory.display import console
from scoped_memory.llm import OpenRouterLLM
from scoped_memory.orchestrator import Orchestrator
from scoped_memory.store import MemoryStore


def handle_command(line: str, orch: Orchestrator) -> bool:
    """Processa um comando /x. Retorna False se for pra sair."""
    cmd, _, arg = line.partition(" ")
    arg = arg.strip()

    if cmd in ("/quit", "/exit"):
        return False
    if cmd == "/help":
        console.print(display.HELP)
    elif cmd == "/user":
        if not arg:
            display.print_error("uso: /user <nome>")
        else:
            orch.set_user(arg)
            display.print_whoami(orch.user_id, orch.team_id)
    elif cmd == "/team":
        if orch.user_id is None:
            display.print_error("defina um usuario antes: /user <nome>")
        elif not arg:
            display.print_error("uso: /team <nome>  (ou /team - para sair do time)")
        else:
            orch.set_team(None if arg == "-" else arg)
            display.print_whoami(orch.user_id, orch.team_id)
    elif cmd == "/whoami":
        display.print_whoami(orch.user_id, orch.team_id)
    elif cmd == "/memories":
        if orch.user_id is None:
            display.print_error("defina um usuario antes: /user <nome>")
        else:
            display.print_memories(orch.user_id, orch.team_id, orch.visible_memories())
    else:
        display.print_error(f"comando desconhecido: {cmd} (veja /help)")
    return True


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="scoped-memory: memoria de agente particionada por usuario/time")
    parser.add_argument("--db", default="memory.db")
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.8-27b:free"))
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        display.print_error("defina OPENROUTER_API_KEY (veja .env.example)")
        sys.exit(1)

    fallbacks = [m.strip() for m in os.environ.get("OPENROUTER_FALLBACK_MODELS", "").split(",") if m.strip()]
    store = MemoryStore(args.db)
    orch = Orchestrator(store, OpenRouterLLM(api_key=api_key, model=args.model, fallback_models=fallbacks))

    display.print_banner(args.model, args.db)
    while True:
        try:
            line = console.input(display.prompt_label(orch.user_id, orch.team_id)).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(line, orch):
                break
            continue
        if orch.user_id is None:
            display.print_error("defina um usuario antes: /user <nome>")
            continue
        try:
            with console.status("[dim]pensando...[/dim]"):
                turn = orch.send(line)
        except Exception as exc:  # erro de rede/rate limit nao derruba a sessao
            display.print_error(f"falha na chamada ao modelo: {exc}")
            continue
        display.print_turn(turn.reply, turn.used_memories, turn.saved)

    store.close()


if __name__ == "__main__":
    main()
