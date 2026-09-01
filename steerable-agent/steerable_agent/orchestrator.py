"""
Orchestrator: o loop principal. Pega o proximo no pending pronto (deps
todas done), executa via Claude, salva o resultado, persiste o checkpoint
inteiro em disco - e, antes de cada no, confere a inbox por uma instrucao
nova do usuario, disparando o replanner se houver uma.

Persistir apos CADA no (nao so no final) e o que torna a execucao
retomavel: se o processo morrer no meio, `Orchestrator(...)` no proximo
`run` carrega o checkpoint e continua exatamente de onde parou, sem
re-executar nada que ja estava done.
"""

from pathlib import Path
from typing import Optional

import anthropic

from . import display
from .planner import create_initial_plan
from .replanner import replan
from .task_graph import TaskGraph

EXECUTE_NODE_SYSTEM_PROMPT = """Voce e um agente executando uma unica tarefa dentro de um \
plano maior. Execute exatamente a tarefa descrita abaixo e responda com o resultado direto \
(o texto que sera usado como entrada por tarefas futuras que dependem desta). Nao descreva o \
que voce vai fazer, apenas produza o resultado."""


class Orchestrator:
    def __init__(
        self,
        objective: Optional[str],
        checkpoint_path: Path,
        inbox_dir: Path,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: Optional[str] = None,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.model = model

        resuming = self.checkpoint_path.exists()
        display.print_banner(objective or "(retomado do checkpoint)", resuming=resuming)

        if resuming:
            self.graph = TaskGraph.load(self.checkpoint_path)
        else:
            if not objective:
                raise ValueError("objetivo e obrigatorio quando nao ha checkpoint existente")
            self.graph = create_initial_plan(objective, self.client, self.model)
            self.graph.save(self.checkpoint_path)
            display.print_initial_plan(self.graph)

    # ------------------------------------------------------------------
    def run(self) -> None:
        while not self.graph.is_complete():
            self._check_inbox()

            if self.graph.is_complete():
                break

            node = self.graph.next_ready_node()
            if node is None:
                if self.graph.is_stuck():
                    display.print_stuck(self.graph)
                    return
                continue  # (nao deveria acontecer em execucao sequencial, mas nao trava)

            self.graph.mark_running(node.id)
            self.graph.save(self.checkpoint_path)
            display.print_node_start(node)

            result_text = self._execute_node(node)

            self.graph.mark_done(node.id, result_text)
            self.graph.save(self.checkpoint_path)
            display.print_node_done(node)

        display.print_complete(self.graph)

    # ------------------------------------------------------------------
    def _check_inbox(self) -> None:
        for path in sorted(self.inbox_dir.glob("*.txt")):
            instruction = path.read_text(encoding="utf-8").strip()
            path.unlink()
            if not instruction:
                continue

            display.print_inbox_instruction(instruction, path.name)
            diff = replan(self.graph, instruction, self.client, self.model)
            result = self.graph.apply_diff(diff)
            display.print_replan_result(result)
            self.graph.save(self.checkpoint_path)

    def _execute_node(self, node) -> str:
        context_parts = []
        for dep_id in node.deps:
            dep = self.graph.get(dep_id)
            if dep and dep.result:
                context_parts.append(f"Resultado de '{dep.description}':\n{dep.result}")
        context = "\n\n".join(context_parts)

        user_message = f"Objetivo geral: {self.graph.objective}\n\nTarefa: {node.description}"
        if context:
            user_message += f"\n\nContexto (resultados de tarefas anteriores):\n{context}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1536,
            system=EXECUTE_NODE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_blocks).strip()
