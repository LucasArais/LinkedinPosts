"""
Orchestrator: sessao de chat com um "usuario ativo" trocavel.

Duas coisas garantem que trocar de usuario na mesma sessao nao mistura
contexto:

  1. O historico de conversa e particionado por user_id (`_histories`).
     Se fosse uma lista unica, o segredo que a alice contou estaria no
     historico enviado ao modelo quando o bob perguntasse - o vazamento
     nem passaria pela memoria persistida.

  2. As memorias injetadas no contexto vem SEMPRE de
     store.search(user_id=<ativo>, team_id=<time do ativo>), e o filtro
     de escopo esta no SQL (ver store.py).

Depois de cada resposta, uma chamada de LLM separada (o "extractor")
decide se algo vale virar memoria e com qual escopo. Memoria de time e
explicita: o extractor so pode marcar scope=team se o usuario tiver um
time ativo E tiver dito na mensagem que aquilo e pro time - essa ultima
checagem e deterministica (regex), fora do modelo.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .llm import LLM
from .store import Memory, MemoryStore

CHAT_SYSTEM = """Voce e um assistente pessoal com memoria de longo prazo. \
Voce esta conversando com o usuario "{user_id}"{team_part}.

{memory_block}

Voce TEM memoria de longo prazo: o sistema grava automaticamente, depois de \
cada mensagem, os fatos que o usuario compartilhar. Entao, quando o usuario pedir \
para voce guardar ou lembrar algo, apenas confirme que vai lembrar.

Use as memorias acima quando forem relevantes. Voce so tem acesso as memorias \
listadas acima: se o usuario perguntar sobre algo (ou sobre outra pessoa) que \
nao esta ali, diga honestamente que voce nao sabe - nunca invente. Responda em \
portugues, de forma curta e direta."""

EXTRACT_SYSTEM = """Voce decide se a ultima mensagem do usuario contem um fato \
que vale guardar como memoria de longo prazo (preferencias, fatos pessoais, \
segredos, decisoes, informacoes uteis no futuro). Perguntas, cumprimentos e \
conversa casual NAO viram memoria.

Responda SOMENTE com um JSON, sem texto extra:
{"save": true|false, "content": "<fato em uma frase, em terceira pessoa, citando o usuario pelo nome>", "scope": "user"|"team"}

scope="team" SOMENTE se o usuario disse explicitamente que a informacao e para o \
time/equipe (ex: "isso e pro time", "avisa a equipe"). Caso contrario, scope="user"."""

# Marcadores explicitos de que algo e "pro time". Guard deterministico:
# mesmo que o extractor diga scope=team, sem isso a memoria fica pessoal.
TEAM_MARKER_RE = re.compile(r"\b(time|equipe|team|galera do time|pessoal do time)\b", re.IGNORECASE)


@dataclass
class TurnResult:
    reply: str
    used_memories: List[Memory]
    saved: Optional[Dict] = None  # {"content", "scope", "ids"} se algo foi gravado


@dataclass
class _UserSession:
    team_id: Optional[str] = None
    history: List[Dict[str, str]] = field(default_factory=list)


def _parse_json_object(text: str) -> Optional[dict]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Orchestrator:
    def __init__(self, store: MemoryStore, llm: LLM, history_turns: int = 10):
        self.store = store
        self.llm = llm
        self.history_turns = history_turns
        self._sessions: Dict[str, _UserSession] = {}
        self.user_id: Optional[str] = None

    # ---------------------------------------------------------- usuario ativo

    def _session(self) -> _UserSession:
        if self.user_id is None:
            raise RuntimeError("nenhum usuario ativo - use set_user() / '/user <nome>' primeiro")
        return self._sessions.setdefault(self.user_id, _UserSession())

    def set_user(self, user_id: str) -> None:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id vazio")
        self.user_id = user_id
        self._sessions.setdefault(user_id, _UserSession())

    def set_team(self, team_id: Optional[str]) -> None:
        team_id = (team_id or "").strip() or None
        self._session().team_id = team_id

    @property
    def team_id(self) -> Optional[str]:
        if self.user_id is None:
            return None
        return self._session().team_id

    def visible_memories(self) -> List[Memory]:
        return self.store.list_visible(self._require_user(), self.team_id)

    def _require_user(self) -> str:
        self._session()
        return self.user_id  # type: ignore[return-value]

    # ---------------------------------------------------------------- chat

    def _build_system(self, memories: List[Memory]) -> str:
        if memories:
            lines = ["Memorias relevantes deste usuario/time:"]
            for m in memories:
                tag = "pessoal" if m.scope_type == "user" else f"time {m.scope_id}"
                lines.append(f"- [{tag}] {m.content}")
            memory_block = "\n".join(lines)
        else:
            memory_block = "Voce ainda nao tem nenhuma memoria sobre este usuario."
        team_part = f' (time "{self.team_id}")' if self.team_id else ""
        return CHAT_SYSTEM.format(user_id=self.user_id, team_part=team_part, memory_block=memory_block)

    def send(self, message: str) -> TurnResult:
        user_id = self._require_user()
        session = self._session()

        memories = self.store.search(message, user_id=user_id, team_id=session.team_id)
        system = self._build_system(memories)

        session.history.append({"role": "user", "content": message})
        window = session.history[-self.history_turns * 2 :]
        reply = self.llm.complete(system, window)
        session.history.append({"role": "assistant", "content": reply})

        saved = self._maybe_remember(message, reply)
        return TurnResult(reply=reply, used_memories=memories, saved=saved)

    # ------------------------------------------------------------ extractor

    def _maybe_remember(self, message: str, reply: str) -> Optional[Dict]:
        prompt = (
            f'Usuario: "{self.user_id}"\n'
            f"Time ativo: {self.team_id or '(nenhum)'}\n\n"
            f"Mensagem do usuario:\n{message}\n\n"
            f"Resposta do assistente:\n{reply}"
        )
        try:
            raw = self.llm.complete(EXTRACT_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=300)
        except Exception:
            return None  # falha no extractor nao derruba a conversa

        data = _parse_json_object(raw)
        if not data or not data.get("save"):
            return None
        content = str(data.get("content") or "").strip()
        if not content:
            return None

        wants_team = data.get("scope") == "team"
        is_team = wants_team and self.team_id is not None and bool(TEAM_MARKER_RE.search(message))
        ids = self.store.add(content, user_id=self.user_id, team_id=self.team_id if is_team else None)
        return {"content": content, "scope": "team" if is_team else "user", "ids": ids}
