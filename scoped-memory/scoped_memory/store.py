"""
MemoryStore: SQLite com particionamento por escopo (user / team).

O ponto central de design e que o isolamento entre usuarios NAO depende
do modelo, nem de filtro em Python depois da busca - ele esta na clausula
WHERE de toda leitura. Nao existe nenhum metodo publico que leia memorias
sem receber um user_id: nao ha `search_all`, nao ha "busca global e
filtra depois". Se um dia alguem quiser ranking semantico (embeddings),
ele roda SOBRE o resultado ja filtrado por escopo, nunca antes.

Regras:
  - memoria pessoal: scope_type='user', scope_id=<user_id>
  - memoria de time: scope_type='team', scope_id=<team_id>, gravada
    SO quando team_id e passado explicitamente em add() - nunca
    promovida automaticamente a partir de memoria pessoal.
  - search() retorna (user AND scope_id=user_id) OR (team AND
    scope_id=team_id). Sem team_id, so a primeira metade.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type  TEXT NOT NULL CHECK (scope_type IN ('user', 'team')),
    scope_id    TEXT NOT NULL CHECK (length(scope_id) > 0),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (scope_type, scope_id);
"""

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Memory:
    id: int
    scope_type: str
    scope_id: str
    content: str
    created_at: str


def _require_id(value: Optional[str], name: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} precisa ser uma string nao vazia")
    return value.strip()


def _tokens(text: str) -> set:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


class MemoryStore:
    def __init__(self, db_path: Union[str, Path] = "memory.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- escrita

    def add(self, content: str, user_id: str, team_id: Optional[str] = None) -> List[int]:
        """Grava a memoria pessoal e, se team_id vier, uma SEGUNDA linha de time.

        Retorna os ids gravados (1 ou 2).
        """
        user_id = _require_id(user_id, "user_id")
        content = (content or "").strip()
        if not content:
            raise ValueError("content nao pode ser vazio")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [("user", user_id)]
        if team_id is not None:
            rows.append(("team", _require_id(team_id, "team_id")))

        ids = []
        with self._conn:
            for scope_type, scope_id in rows:
                cur = self._conn.execute(
                    "INSERT INTO memories (scope_type, scope_id, content, created_at) VALUES (?, ?, ?, ?)",
                    (scope_type, scope_id, content, now),
                )
                ids.append(cur.lastrowid)
        return ids

    # ---------------------------------------------------------------- leitura

    def _visible(self, user_id: str, team_id: Optional[str]) -> List[Memory]:
        """Unico ponto de leitura do banco. O filtro de escopo mora AQUI, no SQL."""
        user_id = _require_id(user_id, "user_id")
        if team_id is None:
            sql = "SELECT * FROM memories WHERE scope_type = 'user' AND scope_id = ? ORDER BY id DESC"
            params: tuple = (user_id,)
        else:
            team_id = _require_id(team_id, "team_id")
            sql = (
                "SELECT * FROM memories "
                "WHERE (scope_type = 'user' AND scope_id = ?) "
                "   OR (scope_type = 'team' AND scope_id = ?) "
                "ORDER BY id DESC"
            )
            params = (user_id, team_id)
        return [Memory(**dict(r)) for r in self._conn.execute(sql, params).fetchall()]

    def list_visible(self, user_id: str, team_id: Optional[str] = None) -> List[Memory]:
        """Tudo que o usuario ativo pode ver agora (usado pelo /memories)."""
        return self._visible(user_id, team_id)

    def search(self, query: str, user_id: str, team_id: Optional[str] = None, limit: int = 8) -> List[Memory]:
        """Busca DENTRO do escopo visivel, ranqueando por sobreposicao de palavras.

        O ranking e propositalmente simples (o MVP e sobre isolamento, nao
        sobre retrieval). Memorias sem nenhuma palavra em comum ainda
        entram, depois das relevantes, ate `limit` - com poucas memorias
        por usuario isso evita que o agente "esqueca" algo so porque a
        pergunta foi feita com outras palavras.
        """
        candidates = self._visible(user_id, team_id)
        q = _tokens(query or "")
        scored = [(len(q & _tokens(m.content)), m) for m in candidates]
        # sort estavel: candidates ja vem do mais novo pro mais antigo
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored[:limit]]
