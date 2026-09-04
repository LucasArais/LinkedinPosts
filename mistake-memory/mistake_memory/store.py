"""
MemoryStore: memoria episodica em SQLite. Cada linha da tabela `episodes`
e uma tentativa registrada - o que foi tentado (approach), pra que tipo
de tarefa (task_signature), e o que aconteceu (outcome + failure_reason).

Duas operacoes de embedding fazem coisas diferentes de proposito:
  - `search_similar` compara a NOVA tarefa contra o task_signature de
    tentativas passadas - "isso parece com algo que ja vi antes?"
  - `add_episode` (dedup) compara a NOVA approach, dentro do MESMO
    task_signature normalizado, contra approaches ja registradas - "essa
    e basicamente a mesma abordagem de novo, ou e algo genuinamente
    diferente?"
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .embeddings import cosine_similarity, embed

DEDUP_APPROACH_SIMILARITY_THRESHOLD = 0.60
BLOCK_MIN_OCCURRENCES = 3


@dataclass
class Episode:
    id: int
    task_signature: str
    run_id: str
    approach: str
    outcome: str
    failure_reason: Optional[str]
    occurrences: int
    created_at: str
    updated_at: str

    @property
    def is_blockable(self) -> bool:
        return self.outcome == "fail" and self.occurrences >= BLOCK_MIN_OCCURRENCES


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_signature TEXT NOT NULL,
                run_id TEXT NOT NULL,
                approach TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK(outcome IN ('success', 'fail')),
                failure_reason TEXT,
                occurrences INTEGER NOT NULL DEFAULT 1,
                task_signature_embedding TEXT NOT NULL,
                approach_embedding TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    def add_episode(
        self,
        task_signature: str,
        run_id: str,
        approach: str,
        outcome: str,
        failure_reason: Optional[str] = None,
    ) -> Episode:
        if outcome not in ("success", "fail"):
            raise ValueError(f"outcome invalido: '{outcome}'")

        now = datetime.now(timezone.utc).isoformat()
        approach_emb = embed(approach)

        existing_row = self._find_duplicate(task_signature, outcome, approach_emb)
        if existing_row is not None:
            self.conn.execute(
                """
                UPDATE episodes
                SET occurrences = occurrences + 1,
                    updated_at = ?,
                    failure_reason = COALESCE(?, failure_reason)
                WHERE id = ?
                """,
                (now, failure_reason, existing_row["id"]),
            )
            self.conn.commit()
            return self._row_to_episode(self._get_row(existing_row["id"]))

        task_sig_emb = embed(task_signature)
        cur = self.conn.execute(
            """
            INSERT INTO episodes
                (task_signature, run_id, approach, outcome, failure_reason, occurrences,
                 task_signature_embedding, approach_embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                task_signature,
                run_id,
                approach,
                outcome,
                failure_reason,
                json.dumps(task_sig_emb.tolist()),
                json.dumps(approach_emb.tolist()),
                now,
                now,
            ),
        )
        self.conn.commit()
        return self._row_to_episode(self._get_row(cur.lastrowid))

    def _find_duplicate(self, task_signature: str, outcome: str, approach_embedding: np.ndarray):
        normalized_sig = task_signature.strip().lower()
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE lower(trim(task_signature)) = ? AND outcome = ?",
            (normalized_sig, outcome),
        ).fetchall()
        for row in rows:
            candidate_emb = np.array(json.loads(row["approach_embedding"]), dtype=np.float32)
            if cosine_similarity(approach_embedding, candidate_emb) >= DEDUP_APPROACH_SIMILARITY_THRESHOLD:
                return row
        return None

    # ------------------------------------------------------------------
    def search_similar(self, task_signature: str, top_k: int = 3) -> List[Tuple[float, Episode]]:
        """
        Retorna ate top_k (similaridade, Episode), priorizando outcome='fail'
        antes de ordenar por similaridade - o objetivo e nunca deixar um
        fracasso relevante cair fora do top_k so porque um sucesso teve
        uma similaridade textual levemente maior.
        """
        query_emb = embed(task_signature)
        rows = self.conn.execute("SELECT * FROM episodes").fetchall()

        scored = []
        for row in rows:
            emb = np.array(json.loads(row["task_signature_embedding"]), dtype=np.float32)
            sim = cosine_similarity(query_emb, emb)
            scored.append((sim, row))

        scored.sort(key=lambda pair: (pair[1]["outcome"] != "fail", -pair[0]))
        top = scored[:top_k]
        return [(sim, self._row_to_episode(row)) for sim, row in top]

    def get_blocking_matches(self, task_signature: str, min_similarity: float = 0.28) -> List[Tuple[float, Episode]]:
        """
        Subconjunto de search_similar que de fato justifica bloqueio: fail,
        occurrences>=3, e similar o suficiente.

        min_similarity=0.28 (nao 0.5) e deliberado: quem chama isso na
        pratica costuma passar a DESCRICAO CRUA da tarefa (o texto que o
        usuario digitou), nao um task_signature ja normalizado - e a
        similaridade entre uma descricao crua e um signature da MESMA
        tarefa fica na faixa de 0.37-0.42 (calibrado empiricamente),
        contra ~0.22 para tarefas genuinamente diferentes. Um threshold de
        0.5 (calibrado para comparar signature-com-signature) deixava
        passar falso-negativo: a checagem de bloqueio nunca via os
        candidatos certos. A precisao real do bloqueio vem da comparacao
        de APPROACH em `Orchestrator._match_blocked_approach` (threshold
        0.60, ver store.py DEDUP_APPROACH_SIMILARITY_THRESHOLD), nao
        deste filtro - este filtro so decide "vale a pena checar essa
        tarefa contra a memoria de bloqueio", nao "bloquear ou nao".
        """
        results = self.search_similar(task_signature, top_k=5)
        return [(sim, ep) for sim, ep in results if ep.is_blockable and sim >= min_similarity]

    # ------------------------------------------------------------------
    def _get_row(self, id_: int):
        return self.conn.execute("SELECT * FROM episodes WHERE id = ?", (id_,)).fetchone()

    @staticmethod
    def _row_to_episode(row: sqlite3.Row) -> Episode:
        return Episode(
            id=row["id"],
            task_signature=row["task_signature"],
            run_id=row["run_id"],
            approach=row["approach"],
            outcome=row["outcome"],
            failure_reason=row["failure_reason"],
            occurrences=row["occurrences"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def all_episodes(self) -> List[Episode]:
        rows = self.conn.execute("SELECT * FROM episodes ORDER BY id").fetchall()
        return [self._row_to_episode(r) for r in rows]

    def close(self) -> None:
        self.conn.close()
