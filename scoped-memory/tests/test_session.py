"""
Testes de sessao: trocar de usuario no MESMO Orchestrator (mesma sessao
CLI, mesmo agente) nao mistura contexto.

Usa um FakeLLM que grava tudo que seria enviado ao modelo - assim da pra
afirmar, sem rede, que o segredo da alice nunca aparece em NENHUM byte do
prompt montado para o bob (nem via memoria, nem via historico).
"""

import json

import pytest

from main import handle_command
from scoped_memory.orchestrator import EXTRACT_SYSTEM, Orchestrator
from scoped_memory.store import MemoryStore

SECRET = "o codigo do cofre e 4815-1623"


class FakeLLM:
    """Chat responde "ok"; extractor salva a mensagem inteira, com scope pedido."""

    def __init__(self, team_scope=False):
        self.calls = []
        self.team_scope = team_scope

    def complete(self, system, messages, max_tokens=800):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if system == EXTRACT_SYSTEM:
            msg = messages[-1]["content"].split("Mensagem do usuario:\n", 1)[1].split("\n\nResposta", 1)[0]
            if msg.endswith("?"):
                return json.dumps({"save": False})
            scope = "team" if self.team_scope else "user"
            return f"```json\n{json.dumps({'save': True, 'content': msg, 'scope': scope})}\n```"
        return "ok"

    def chat_calls(self):
        return [c for c in self.calls if c["system"] != EXTRACT_SYSTEM]


def _dump(call):
    return call["system"] + "\n" + "\n".join(m["content"] for m in call["messages"])


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


def test_switching_user_does_not_leak_memory_or_history(store):
    llm = FakeLLM()
    orch = Orchestrator(store, llm)

    orch.set_user("alice")
    turn = orch.send(f"Guarda isso: {SECRET}")
    assert turn.saved and turn.saved["scope"] == "user"

    orch.set_user("bob")
    llm.calls.clear()
    turn = orch.send("Qual e o codigo do cofre da alice?")

    assert turn.used_memories == []
    for call in llm.calls:  # chat E extractor
        assert "4815-1623" not in _dump(call)
    # historico do bob comeca do zero
    assert llm.chat_calls()[0]["messages"] == [{"role": "user", "content": "Qual e o codigo do cofre da alice?"}]


def test_switching_back_restores_own_history_and_memory(store):
    llm = FakeLLM()
    orch = Orchestrator(store, llm)

    orch.set_user("alice")
    orch.send(f"Guarda isso: {SECRET}")
    orch.set_user("bob")
    orch.send("Eu gosto de cha.")
    orch.set_user("alice")
    llm.calls.clear()
    orch.send("Qual e o codigo do cofre?")

    prompt = _dump(llm.chat_calls()[0])
    assert "4815-1623" in prompt  # a alice ainda ve o proprio segredo
    assert "cha" not in prompt.lower().split()  # e nao ve nada do bob
    assert "Eu gosto de cha." not in prompt


def test_same_team_members_share_only_team_memory(store):
    orch = Orchestrator(store, FakeLLM(team_scope=True))

    orch.set_user("alice")
    orch.set_team("eng")
    orch.send(f"Pessoal: {SECRET}")  # sem marcador de time -> fica pessoal mesmo com scope=team do LLM
    turn = orch.send("Isso e pro time: deploy congelado na sexta")
    assert turn.saved["scope"] == "team"

    orch.set_user("bob")
    orch.set_team("eng")
    visible = [m.content for m in orch.visible_memories()]
    assert any("deploy congelado" in c for c in visible)
    assert not any("4815-1623" in c for c in visible)


def test_team_scope_requires_active_team(store):
    orch = Orchestrator(store, FakeLLM(team_scope=True))
    orch.set_user("alice")
    turn = orch.send("Isso e pro time: retro quinta 16h")
    assert turn.saved["scope"] == "user"
    assert all(m.scope_type == "user" for m in store.list_visible("alice", "eng"))


def test_team_is_per_user_in_session(store):
    orch = Orchestrator(store, FakeLLM())
    orch.set_user("alice")
    orch.set_team("eng")
    orch.set_user("bob")
    assert orch.team_id is None  # bob nao herda o time da alice
    orch.set_user("alice")
    assert orch.team_id == "eng"


def test_cli_commands_switch_context_without_deleting_memory(store, capsys):
    llm = FakeLLM()
    orch = Orchestrator(store, llm)

    handle_command("/user alice", orch)
    orch.send(f"Guarda isso: {SECRET}")
    handle_command("/user bob", orch)
    assert handle_command("/memories", orch) is True
    assert "4815-1623" not in capsys.readouterr().out

    handle_command("/user alice", orch)
    handle_command("/memories", orch)
    assert "4815-1623" in capsys.readouterr().out
    assert handle_command("/quit", orch) is False


def test_extractor_garbage_does_not_break_turn(store):
    class Broken(FakeLLM):
        def complete(self, system, messages, max_tokens=800):
            return "nao sei fazer json" if system == EXTRACT_SYSTEM else "ok"

    orch = Orchestrator(store, Broken())
    orch.set_user("alice")
    turn = orch.send("qualquer coisa")
    assert turn.reply == "ok" and turn.saved is None
