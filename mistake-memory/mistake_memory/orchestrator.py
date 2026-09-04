"""
Orchestrator: costura tudo. O ponto central de design e que a checagem de
bloqueio acontece em DOIS momentos diferentes, por bons motivos:

  1. ANTES do agente tentar - busca as tarefas parecidas na memoria e
     injeta um aviso no contexto (requisito 3). Isso e so um "empurrao",
     nao impede nada por si so - um LLM pode ignorar instrucao de texto.

  2. DEPOIS que o agente DECLARA a abordagem (no mesmo tool call que
     produz a correcao, ver agent.py) mas ANTES de aceitar/aplicar essa
     correcao - aqui e onde o bloqueio de verdade acontece (requisito 5).
     A abordagem declarada e comparada, por embedding, contra as
     abordagens ja marcadas como reprovadas (fail, occurrences>=3) para
     tarefas parecidas. Se bater, a tentativa e recusada e o
     fixed_file_content do agente e descartado sem nunca ser escrito em
     disco nem testado - o enforcement fica fora do modelo, igual aos
     projetos irmaos desta serie.
"""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import anthropic

from . import display
from .agent import attempt_fix
from .embeddings import cosine_similarity, embed
from .recorder import record_attempt
from .store import DEDUP_APPROACH_SIMILARITY_THRESHOLD, MemoryStore


class BlockedApproachError(Exception):
    def __init__(self, matches):
        self.matches = matches
        super().__init__("abordagem bloqueada pela memoria episodica")


def _build_memory_context(results) -> str:
    if not results:
        return ""
    lines = ["ATENCAO: abordagens ja tentadas para tarefas parecidas, extraidas da memoria episodica:"]
    for sim, ep in results:
        lines.append(
            f"- approach: \"{ep.approach}\" | outcome: {ep.outcome} | "
            f"occurrences: {ep.occurrences} | failure_reason: {ep.failure_reason or '-'}"
        )
    lines.append(
        "Nao repita uma abordagem marcada como fail sem justificar, no campo 'diagnosis', "
        "por que dessa vez seria diferente."
    )
    return "\n".join(lines)


def _run_pytest(target_file: Path, test_file: Path, fixed_content: str) -> "tuple[bool, str]":
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = Path(tmpdir) / target_file.name
        tmp_test = Path(tmpdir) / test_file.name
        tmp_target.write_text(fixed_content, encoding="utf-8")
        shutil.copy(test_file, tmp_test)

        proc = subprocess.run(
            ["python3", "-m", "pytest", tmp_test.name, "-v"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        passed = proc.returncode == 0
        output = proc.stdout + proc.stderr
        return passed, output


class Orchestrator:
    def __init__(
        self,
        db_path: Path,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: Optional[str] = None,
        force: bool = False,
    ):
        self.store = MemoryStore(db_path)
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.model = model
        self.force = force
        self.run_id = str(uuid.uuid4())[:8]

    def run(self, task_description: str, target_file: Path, test_file: Path) -> None:
        display.print_banner(task_description, self.run_id)

        similar = self.store.search_similar(task_description, top_k=3)
        display.print_memory_lookup(similar)

        blocking_candidates = self.store.get_blocking_matches(task_description)

        memory_context = _build_memory_context(similar)

        file_content = target_file.read_text(encoding="utf-8")
        test_content = test_file.read_text(encoding="utf-8")

        attempt = attempt_fix(task_description, file_content, test_content, memory_context, self.client, self.model)
        diagnosis, approach, fixed_content = attempt["diagnosis"], attempt["approach"], attempt["fixed_file_content"]
        display.print_attempt(diagnosis, approach)

        matched_block = self._match_blocked_approach(approach, blocking_candidates)
        if matched_block is not None:
            display.print_blocked([matched_block], force=self.force)
            if not self.force:
                self.store.close()
                return  # execucao recusada - nada e escrito, nada e testado, nada e registrado

        passed, test_output = _run_pytest(target_file, test_file, fixed_content)
        display.print_test_result(passed, test_output)

        transcript = (
            f"Tarefa: {task_description}\n"
            f"Diagnostico do agente: {diagnosis}\n"
            f"Abordagem tentada: {approach}\n"
            f"Resultado real do teste (pytest, {'passou' if passed else 'falhou'}):\n{test_output}"
        )
        record = record_attempt(transcript, self.client, self.model)

        episode = self.store.add_episode(
            task_signature=record["task_signature"],
            run_id=self.run_id,
            approach=record["approach"],
            outcome=record["outcome"],
            failure_reason=record.get("failure_reason"),
        )
        display.print_recorded(episode.task_signature, episode.approach, episode.outcome, episode.failure_reason, episode.occurrences)

        self.store.close()

    @staticmethod
    def _match_blocked_approach(approach: str, blocking_candidates):
        if not blocking_candidates:
            return None
        approach_emb = embed(approach)
        for sim, ep in blocking_candidates:
            approach_sim = cosine_similarity(approach_emb, embed(ep.approach))
            if approach_sim >= DEDUP_APPROACH_SIMILARITY_THRESHOLD:
                return (approach_sim, ep)
        return None
