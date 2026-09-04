"""
Testes do MemoryStore. Usam embeddings locais de verdade (sentence-
transformers, sem rede apos o modelo estar em cache) - nao precisam de
ANTHROPIC_API_KEY. Cada teste usa um arquivo de banco temporario proprio.
"""

import pytest

from mistake_memory.store import BLOCK_MIN_OCCURRENCES, MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


def test_add_episode_creates_new_row(store):
    ep = store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason="o loop de retry sai na primeira falha, aumentar o numero nao muda nada",
    )
    assert ep.occurrences == 1
    assert ep.outcome == "fail"
    assert len(store.all_episodes()) == 1


def test_add_episode_dedups_similar_approach_same_signature(store):
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason="nao retenta de verdade",
    )
    # mesma ideia, frase diferente, mesmo task_signature -> deve incrementar, nao duplicar
    ep2 = store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-2",
        approach="elevar max_retries de 3 para 10 tentativas",
        outcome="fail",
        failure_reason="ainda nao retenta de verdade",
    )
    assert ep2.occurrences == 2
    assert len(store.all_episodes()) == 1


def test_add_episode_does_not_dedup_different_approach(store):
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason="nao retenta de verdade",
    )
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-2",
        approach="trocar o break por continue no loop de retry",
        outcome="success",
    )
    episodes = store.all_episodes()
    assert len(episodes) == 2
    outcomes = {e.outcome for e in episodes}
    assert outcomes == {"fail", "success"}


def test_add_episode_does_not_dedup_different_task_signature(store):
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="aumentar max_retries",
        outcome="fail",
    )
    store.add_episode(
        task_signature="corrigir vazamento de memoria no cache",
        run_id="run-2",
        approach="aumentar max_retries",  # mesma approach, mas tarefa diferente
        outcome="fail",
    )
    assert len(store.all_episodes()) == 2


def test_add_episode_updates_failure_reason_on_dedup(store):
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason=None,
    )
    ep2 = store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-2",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason="o loop sai na primeira excecao, retries extras nunca acontecem",
    )
    assert ep2.failure_reason == "o loop sai na primeira excecao, retries extras nunca acontecem"


def test_search_similar_prioritizes_fail_over_higher_similarity_success(store):
    # 'success' com texto quase identico a query
    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-1",
        approach="trocar break por continue",
        outcome="success",
    )
    # 'fail' com texto um pouco menos parecido
    store.add_episode(
        task_signature="consertar teste de rede instavel",
        run_id="run-2",
        approach="aumentar max_retries",
        outcome="fail",
        failure_reason="nao retenta de verdade",
    )
    results = store.search_similar("corrigir teste flaky de rede", top_k=2)
    assert results[0][1].outcome == "fail"  # fail vem primeiro mesmo com similaridade textual menor


def test_search_similar_returns_empty_for_empty_store(store):
    assert store.search_similar("qualquer coisa") == []


def test_get_blocking_matches_requires_min_occurrences(store):
    for i in range(BLOCK_MIN_OCCURRENCES - 1):
        store.add_episode(
            task_signature="corrigir teste flaky de rede",
            run_id=f"run-{i}",
            approach="aumentar max_retries de 3 para 10",
            outcome="fail",
            failure_reason="nao retenta de verdade",
        )
    # ainda abaixo do limite -> nao bloqueia
    assert store.get_blocking_matches("corrigir teste flaky de rede") == []

    store.add_episode(
        task_signature="corrigir teste flaky de rede",
        run_id="run-final",
        approach="aumentar max_retries de 3 para 10",
        outcome="fail",
        failure_reason="nao retenta de verdade",
    )
    matches = store.get_blocking_matches("corrigir teste flaky de rede")
    assert len(matches) == 1
    assert matches[0][1].occurrences == BLOCK_MIN_OCCURRENCES


def test_get_blocking_matches_finds_candidate_from_raw_task_description(store):
    """
    Regressao de um bug real encontrado na validacao ao vivo: o threshold
    original (0.5) foi calibrado comparando task_signature com
    task_signature, mas na pratica quem chama get_blocking_matches passa
    a DESCRICAO CRUA que o usuario digitou (nao um signature ja
    normalizado) - a similaridade entre os dois fica bem mais baixa
    (~0.37-0.42 mesmo para a mesma tarefa) do que entre dois signatures.
    Com o threshold antigo, o bloqueio nunca via o candidato certo.
    """
    for i in range(BLOCK_MIN_OCCURRENCES):
        store.add_episode(
            task_signature="corrigir teste flaky de rede",
            run_id=f"seed-{i}",
            approach="aumentar max_retries de 3 para 10",
            outcome="fail",
            failure_reason="o loop de retry sai na primeira excecao, aumentar o numero nao muda nada",
        )
    raw_task_description = (
        "o teste de rede em examples/buggy_code/network_client.py está falhando de vez em quando"
    )
    matches = store.get_blocking_matches(raw_task_description)
    assert len(matches) == 1
    assert matches[0][1].approach == "aumentar max_retries de 3 para 10"


def test_get_blocking_matches_ignores_success_regardless_of_occurrences(store):
    for i in range(5):
        store.add_episode(
            task_signature="corrigir teste flaky de rede",
            run_id=f"run-{i}",
            approach="trocar break por continue",
            outcome="success",
        )
    assert store.get_blocking_matches("corrigir teste flaky de rede") == []
