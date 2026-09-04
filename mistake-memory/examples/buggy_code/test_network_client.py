"""
Teste "flaky" que a tarefa de demo pede pra corrigir. Falha na maior
parte das rodadas com o bug original (break sai do retry na primeira
falha -> taxa de sucesso ~30%, so quando a 1a tentativa da certo).
Com o retry de verdade (max_retries=5, ~70% de falha por tentativa),
a taxa de sucesso esperada sobe pra ~83%.
"""

from network_client import fetch_with_retry, TransientNetworkError

TRIALS = 50
MAX_RETRIES = 5
MIN_SUCCESS_RATE = 0.65  # bem entre ~30% (com bug) e ~83% (corrigido)


def test_fetch_with_retry_eventually_succeeds_most_of_the_time():
    successes = 0
    for seed in range(TRIALS):
        try:
            result = fetch_with_retry(max_retries=MAX_RETRIES, seed=seed)
            if result == "response-ok":
                successes += 1
        except TransientNetworkError:
            pass

    rate = successes / TRIALS
    assert rate >= MIN_SUCCESS_RATE, (
        f"taxa de sucesso {rate:.0%} ({successes}/{TRIALS}) abaixo do esperado ({MIN_SUCCESS_RATE:.0%}) "
        f"- o retry parece nao estar tentando de novo de verdade"
    )
