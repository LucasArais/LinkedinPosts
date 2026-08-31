"""
CircuitBreaker: fica entre a decisao do modelo (qual ferramenta chamar, com
quais argumentos) e a execucao real dessa ferramenta. Nunca confia na
intencao do modelo - toda chamada e revalidada aqui contra a allowlist
declarada na TaskProfile, independente do que o system prompt ou o
conteudo lido pelo agente tenha tentado instruir.

Ordem de verificacao (a primeira que bloquear, vence):
  1. kill switch  - aborta tudo, sem excecao, mesmo chamadas dentro do escopo
  2. limite de chamadas por sessao
  3. a ferramenta esta na allowlist da tarefa?
  4. (so para run_shell) o comando bate com a allowlist de comandos da tarefa?

Qualquer bloqueio nos passos 3 e 4 pausa a execucao e pede confirmacao
humana (via confirm_fn). Se a pessoa aprovar, a chamada prossegue e fica
registrada como 'approved_by_human'; se negar (ou o modo nao for
interativo), a sessao inteira e interrompida com GuardrailBlocked - o
agente nao tenta outra ferramenta em seguida, o circuito abre de vez.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .audit_log import AuditLogger
from .kill_switch import is_kill_switch_active
from .tasks import TaskProfile


class Decision(str, Enum):
    APPROVED = "approved"
    APPROVED_BY_HUMAN = "approved_by_human"
    BLOCKED_KILL_SWITCH = "blocked_kill_switch"
    BLOCKED_CALL_LIMIT = "blocked_call_limit"
    BLOCKED_SCOPE = "blocked_scope"
    BLOCKED_SHELL_COMMAND = "blocked_shell_command"


@dataclass
class BreakerResult:
    decision: Decision
    reason: str


class GuardrailBlocked(Exception):
    """Levantada quando o circuito abre e a sessao deve parar imediatamente."""

    def __init__(self, decision: Decision, reason: str):
        self.decision = decision
        self.reason = reason
        super().__init__(reason)


ConfirmFn = Callable[[str, dict, str], bool]


class CircuitBreaker:
    def __init__(
        self,
        task_profile: TaskProfile,
        audit_logger: AuditLogger,
        interactive: bool = True,
        confirm_fn: Optional[ConfirmFn] = None,
    ):
        self.task_profile = task_profile
        self.audit_logger = audit_logger
        self.interactive = interactive
        self._confirm_fn = confirm_fn or self._default_confirm
        self.call_count = 0

    def _default_confirm(self, tool_name: str, tool_args: dict, reason: str) -> bool:
        if not self.interactive:
            return False
        print("\n[GUARDRAILS] Chamada fora do escopo da tarefa detectada:")
        print(f"  ferramenta: {tool_name}")
        print(f"  argumentos: {tool_args}")
        print(f"  motivo:     {reason}")
        resp = input("  Aprovar mesmo assim? [y/N] ").strip().lower()
        return resp in ("y", "yes", "s", "sim")

    def _shell_command_allowed(self, command: str) -> bool:
        return any(
            re.fullmatch(pattern, command) for pattern in self.task_profile.allowed_shell_commands
        )

    def _ask_and_resolve(
        self, step: int, tool_name: str, tool_args: dict, reason: str, blocked_decision: Decision
    ) -> BreakerResult:
        approved = self._confirm_fn(tool_name, tool_args, reason)
        if approved:
            decision = Decision.APPROVED_BY_HUMAN
            self.audit_logger.log_decision(step, tool_name, tool_args, decision.value, reason)
            self.call_count += 1
            return BreakerResult(decision, reason)

        self.audit_logger.log_decision(step, tool_name, tool_args, blocked_decision.value, reason)
        raise GuardrailBlocked(blocked_decision, reason)

    def evaluate(self, step: int, tool_name: str, tool_args: dict) -> BreakerResult:
        # 1. Kill switch: nao importa mais nada, aborta na hora.
        if is_kill_switch_active():
            reason = "Kill switch ativo (env var ou arquivo KILL_SWITCH presente)"
            self.audit_logger.log_decision(
                step, tool_name, tool_args, Decision.BLOCKED_KILL_SWITCH.value, reason
            )
            raise GuardrailBlocked(Decision.BLOCKED_KILL_SWITCH, reason)

        # 2. Limite de chamadas de ferramenta por sessao.
        if self.call_count >= self.task_profile.max_tool_calls:
            reason = f"Limite de {self.task_profile.max_tool_calls} chamadas de ferramenta por sessao atingido"
            self.audit_logger.log_decision(
                step, tool_name, tool_args, Decision.BLOCKED_CALL_LIMIT.value, reason
            )
            raise GuardrailBlocked(Decision.BLOCKED_CALL_LIMIT, reason)

        # 3. A ferramenta esta na allowlist desta tarefa?
        if tool_name not in self.task_profile.allowed_tools:
            reason = (
                f"Ferramenta '{tool_name}' fora da allowlist da tarefa "
                f"'{self.task_profile.task_id}' (permitidas: {self.task_profile.allowed_tools})"
            )
            return self._ask_and_resolve(step, tool_name, tool_args, reason, Decision.BLOCKED_SCOPE)

        # 4. Caso especial: run_shell precisa bater com a allowlist de comandos.
        if tool_name == "run_shell":
            command = tool_args.get("command", "")
            if not self._shell_command_allowed(command):
                reason = (
                    f"Comando '{command}' nao esta na allowlist de shell da tarefa "
                    f"'{self.task_profile.task_id}' (permitidos: {self.task_profile.allowed_shell_commands or '[]'})"
                )
                return self._ask_and_resolve(
                    step, tool_name, tool_args, reason, Decision.BLOCKED_SHELL_COMMAND
                )

        # 5. Dentro do escopo.
        self.call_count += 1
        reason = "Dentro da allowlist da tarefa"
        self.audit_logger.log_decision(step, tool_name, tool_args, Decision.APPROVED.value, reason)
        return BreakerResult(Decision.APPROVED, reason)
