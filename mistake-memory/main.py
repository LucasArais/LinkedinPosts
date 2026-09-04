"""
CLI do mistake-memory.

Uso:
    python main.py "descricao da tarefa"
    python main.py "descricao da tarefa" --force   # ignora bloqueio de abordagem ja reprovada

Cada execucao e uma sessao nova (sem historico de conversa entre
execucoes) - o unico "estado" entre sessoes e o que esta persistido em
memory.db.
"""

import argparse
import os
import sys
from pathlib import Path

from mistake_memory.display import console
from mistake_memory.orchestrator import Orchestrator

DEFAULT_TARGET = Path("examples/buggy_code/network_client.py")
DEFAULT_TEST = Path("examples/buggy_code/test_network_client.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="mistake-memory: memoria episodica com enforcement")
    parser.add_argument("task", help="Descricao da tarefa em linguagem natural")
    parser.add_argument("--force", action="store_true", help="Ignora bloqueio de abordagem ja reprovada")
    parser.add_argument("--db", default="memory.db")
    parser.add_argument("--target-file", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--test-file", type=Path, default=DEFAULT_TEST)
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    parser.add_argument("--base-url", default=os.environ.get("ANTHROPIC_BASE_URL"))
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]ERRO:[/bold red] defina a variavel de ambiente ANTHROPIC_API_KEY")
        sys.exit(1)

    if not args.target_file.exists() or not args.test_file.exists():
        console.print(f"[bold red]ERRO:[/bold red] arquivo(s) nao encontrado(s): {args.target_file}, {args.test_file}")
        sys.exit(1)

    orchestrator = Orchestrator(
        db_path=Path(args.db),
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        force=args.force,
    )
    orchestrator.run(args.task, args.target_file, args.test_file)


if __name__ == "__main__":
    main()
