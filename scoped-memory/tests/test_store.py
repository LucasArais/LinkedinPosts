"""
Testes do MemoryStore - o "teste de vazamento" mora aqui.

Todos deterministicos, sem rede: o isolamento e uma propriedade do SQL,
nao do modelo, entao da pra provar sem chamar LLM nenhum.
"""

import sqlite3

import pytest

from scoped_memory.store import MemoryStore

ALICE_SECRET = "O codigo do cofre da alice e 4815-1623"


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


def _contents(memories):
    return [m.content for m in memories]


# --------------------------------------------------------------- vazamento


def test_leak_alice_personal_memory_never_reaches_bob(store):
    store.add(ALICE_SECRET, user_id="alice")

    # bob busca com a frase EXATA do segredo - melhor caso possivel pro ranking
    assert ALICE_SECRET not in _contents(store.search(ALICE_SECRET, user_id="bob"))
    assert ALICE_SECRET not in _contents(store.list_visible(user_id="bob"))
    # e a alice continua vendo
    assert ALICE_SECRET in _contents(store.search("cofre", user_id="alice"))


def test_leak_same_team_does_not_expose_personal_memory(store):
    """Mesmo team_id NAO abre a memoria pessoal de outro membro."""
    store.add(ALICE_SECRET, user_id="alice")  # pessoal, sem team_id

    for query in (ALICE_SECRET, "cofre", "alice", ""):
        results = store.search(query, user_id="bob", team_id="team-eng")
        assert ALICE_SECRET not in _contents(results)
        assert all(not (m.scope_type == "user" and m.scope_id != "bob") for m in results)


def test_leak_personal_memory_stays_private_even_when_alice_also_writes_to_team(store):
    store.add(ALICE_SECRET, user_id="alice")
    store.add("Deploy de sexta esta congelado", user_id="alice", team_id="team-eng")

    bob_sees = store.search("cofre deploy", user_id="bob", team_id="team-eng")
    assert _contents(bob_sees) == ["Deploy de sexta esta congelado"]
    assert bob_sees[0].scope_type == "team"


def test_leak_many_users_only_ever_see_their_own(store):
    users = [f"user{i}" for i in range(20)]
    for u in users:
        store.add(f"segredo exclusivo de {u}", user_id=u, team_id=None)
        store.add(f"nota de time de {u}", user_id=u, team_id="team-all")

    for u in users:
        results = store.list_visible(user_id=u, team_id="team-all")
        personal = [m for m in results if m.scope_type == "user"]
        assert [m.scope_id for m in personal] == [u, u]  # a pessoal + a copia pessoal da nota de time
        assert all(m.scope_id == "team-all" for m in results if m.scope_type == "team")
        for other in users:
            if other != u:
                assert f"segredo exclusivo de {other}" not in _contents(results)


def test_leak_sql_injection_in_user_id_does_not_widen_scope(store):
    store.add(ALICE_SECRET, user_id="alice")
    for evil in ("bob' OR '1'='1", "bob') OR (1=1", "%", "*"):
        assert store.search("cofre", user_id=evil) == []
        assert store.search("cofre", user_id="bob", team_id=evil) == []


# --------------------------------------------------------------- time


def test_add_with_team_writes_two_rows(store):
    ids = store.add("Retro toda quinta 16h", user_id="alice", team_id="team-eng")
    assert len(ids) == 2
    rows = {(m.scope_type, m.scope_id) for m in store.list_visible("alice", "team-eng")}
    assert rows == {("user", "alice"), ("team", "team-eng")}


def test_team_memory_visible_to_both_members(store):
    store.add("Retro toda quinta 16h", user_id="alice", team_id="team-eng")

    for member in ("alice", "bob"):
        results = store.search("retro", user_id=member, team_id="team-eng")
        assert "Retro toda quinta 16h" in _contents(results)


def test_team_memory_not_visible_outside_team_or_without_team(store):
    store.add("Retro toda quinta 16h", user_id="alice", team_id="team-eng")

    assert store.search("retro", user_id="carol", team_id="team-sales") == []
    assert store.search("retro", user_id="bob") == []  # bob sem time ativo


def test_personal_memory_is_never_auto_promoted_to_team(store):
    store.add(ALICE_SECRET, user_id="alice")
    team_rows = [m for m in store.list_visible("alice", "team-eng") if m.scope_type == "team"]
    assert team_rows == []


# --------------------------------------------------------------- validacao


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_empty_user_id_is_rejected(store, bad):
    with pytest.raises(ValueError):
        store.add("x", user_id=bad)
    with pytest.raises(ValueError):
        store.search("x", user_id=bad)


def test_empty_team_id_is_rejected_instead_of_matching_nothing_silently(store):
    with pytest.raises(ValueError):
        store.add("x", user_id="alice", team_id="")
    with pytest.raises(ValueError):
        store.search("x", user_id="alice", team_id="  ")


def test_schema_rejects_invalid_scope_type(store):
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO memories (scope_type, scope_id, content, created_at) VALUES ('global', 'x', 'y', 'z')"
        )


def test_search_ranks_relevant_first(store):
    store.add("Prefere cafe sem acucar", user_id="alice")
    store.add("Mora em Belo Horizonte", user_id="alice")
    results = store.search("onde a alice mora? horizonte", user_id="alice")
    assert results[0].content == "Mora em Belo Horizonte"
