"""
Ponto de entrada CLI do guarded-agent.

Exemplos:
  python main.py --task-profile organize_csv_by_month \\
      --prompt "Organize os csv de examples/downloads_demo por mes" \\
      --dry-run

  python main.py --task-profile organize_csv_by_month \\
      --prompt "Organize os csv de examples/downloads_demo por mes" \\
      --non-interactive
"""

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.core import GuardedAgent  # noqa: E402
from guardrails.tasks import TASK_PROFILES, get_task_profile  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente autonomo com camada de guardrails.")
    parser.add_argument("--task-profile", required=True, choices=list(TASK_PROFILES.keys()))
    parser.add_argument("--prompt", required=True, help="Instrucao em linguagem natural para o agente")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria feito, sem executar")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Nunca pede confirmacao humana; nega automaticamente chamadas fora de escopo",
    )
    parser.add_argument("--max-calls", type=int, default=None, help="Sobrescreve max_tool_calls da tarefa")
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    parser.add_argument("--log-path", default="logs/audit.jsonl")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ANTHROPIC_BASE_URL"),
        help="Endpoint alternativo compativel com a Anthropic Messages API (ex: gateway/proxy)",
    )
    args = parser.parse_args()

    profile = get_task_profile(args.task_profile)
    if args.max_calls is not None:
        profile = replace(profile, max_tool_calls=args.max_calls)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERRO: defina a variavel de ambiente ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    agent = GuardedAgent(
        task_profile=profile,
        api_key=api_key,
        model=args.model,
        dry_run=args.dry_run,
        interactive=not args.non_interactive,
        log_path=args.log_path,
        base_url=args.base_url,
    )

    print(f"[+] Sessao {agent.session_id} | tarefa={profile.task_id} | dry_run={args.dry_run}")
    print(f"[+] Log de auditoria: {args.log_path}")
    result = agent.run(args.prompt)
    print("\n=== RESULTADO ===")
    print(result)


if __name__ == "__main__":
    main()
