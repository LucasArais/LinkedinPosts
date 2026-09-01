"""
CLI do steerable-agent.

Uso:
    python main.py "objetivo da tarefa"     # inicia um plano novo (ou recusa se ja houver checkpoint)
    python main.py                           # retoma o checkpoint existente

Durante a execucao, solte um arquivo .txt em ./inbox/ a qualquer momento
para injetar uma nova instrucao - o orquestrador le, apaga o arquivo, e
replaneja antes de pegar a proxima tarefa.
"""

import argparse
import os
import sys
from pathlib import Path

from steerable_agent.display import console
from steerable_agent.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="steerable-agent: orquestrador de plano com replan em runtime")
    parser.add_argument("objective", nargs="?", help="Objetivo da tarefa (obrigatorio se nao houver checkpoint)")
    parser.add_argument("--checkpoint", default="checkpoint.json")
    parser.add_argument("--inbox-dir", default="inbox")
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    parser.add_argument("--base-url", default=os.environ.get("ANTHROPIC_BASE_URL"))
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint)
    if not checkpoint_path.exists() and not args.objective:
        console.print(
            "[bold red]ERRO:[/bold red] nao ha checkpoint existente - forneca um objetivo:\n"
            '  python main.py "organize uma pesquisa de mercado sobre X"'
        )
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]ERRO:[/bold red] defina a variavel de ambiente ANTHROPIC_API_KEY")
        sys.exit(1)

    orchestrator = Orchestrator(
        objective=args.objective,
        checkpoint_path=checkpoint_path,
        inbox_dir=Path(args.inbox_dir),
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
