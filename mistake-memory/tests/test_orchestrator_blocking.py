"""
Prova determinística do mecanismo de bloqueio (requisito central do
projeto). Não depende de nenhuma chamada de API - constrói o estado da
memória diretamente (3 episódios 'fail' da mesma abordagem) e verifica
que `Orchestrator._match_blocked_approach` reconhece uma abordagem nova
(parafraseada, não texto idêntico) como a mesma abordagem já reprovada, e
que uma abordagem genuinamente diferente passa livre.

Esse é o mesmo princípio dos três projetos irmãos desta série
(guarded-agent, browser-sandbox, steerable-agent): a prova real é o teste
que força o cenário de bloqueio diretamente, não a esperança de que um
agente ao vivo vá "cair na armadilha" - inclusive porque, na validação ao
vivo deste projeto, ele não caiu (ver README).
"""

import pytest

from mistake_memory.orchestrator import Orchestrator
from mistake_memory.store import BLOCK_MIN_OCCURRENCES, MemoryStore


@pytest.fixture
def store_with_blocked_approach(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    for i in range(BLOCK_MIN_OCCURRENCES):
        store.add_episode(
            task_signature="corrigir teste flaky de rede",
            run_id=f"seed-{i}",
            approach="aumentar max_retries de 3 para 10",
            outcome="fail",
            failure_reason="o loop de retry sai (break) na primeira excecao, aumentar o numero nao muda nada",
        )
    yield store
    store.close()


def test_blocking_matches_found_for_seeded_failure(store_with_blocked_approach):
    matches = store_with_blocked_approach.get_blocking_matches("corrigir teste flaky de rede")
    assert len(matches) == 1
    assert matches[0][1].occurrences == BLOCK_MIN_OCCURRENCES


def test_match_blocked_approach_catches_paraphrased_repeat(store_with_blocked_approach):
    blocking_candidates = store_with_blocked_approach.get_blocking_matches("corrigir teste flaky de rede")

    # frase diferente, mesma ideia - e assim que um agente real reformularia
    paraphrased = "Elevar o valor de max_retries de 3 para 10 tentativas"
    match = Orchestrator._match_blocked_approach(paraphrased, blocking_candidates)

    assert match is not None
    similarity, episode = match
    assert episode.approach == "aumentar max_retries de 3 para 10"
    assert similarity >= 0.60


def test_match_blocked_approach_allows_genuinely_different_fix(store_with_blocked_approach):
    blocking_candidates = store_with_blocked_approach.get_blocking_matches("corrigir teste flaky de rede")

    real_fix = "Remover o break do bloco except para permitir que o loop de retry continue tentando"
    match = Orchestrator._match_blocked_approach(real_fix, blocking_candidates)

    assert match is None  # abordagem genuinamente diferente - nao deveria ser bloqueada


def test_match_blocked_approach_returns_none_without_candidates():
    assert Orchestrator._match_blocked_approach("qualquer abordagem", []) is None


def test_blocking_requires_minimum_occurrences(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    for i in range(BLOCK_MIN_OCCURRENCES - 1):  # um a menos que o limite
        store.add_episode(
            task_signature="corrigir teste flaky de rede",
            run_id=f"seed-{i}",
            approach="aumentar max_retries de 3 para 10",
            outcome="fail",
        )
    matches = store.get_blocking_matches("corrigir teste flaky de rede")
    assert matches == []

    # a abordagem parafraseada NAO deve ser bloqueada ainda
    match = Orchestrator._match_blocked_approach("elevar max_retries para 10", matches)
    assert match is None
    store.close()
