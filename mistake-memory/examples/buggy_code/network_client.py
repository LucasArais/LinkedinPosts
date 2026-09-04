"""
Cliente de rede com um bug de "retry" que nao retenta de verdade.

A cilada: o codigo TEM um for loop de max_retries, TEM um try/except em
volta da chamada flaky - parece corrigivel so aumentando max_retries ou
adicionando um sleep entre tentativas. Mas o bug real e o `break` dentro
do except: ele sai do loop de retry na PRIMEIRA falha, independente de
quantas tentativas ainda restariam. Aumentar max_retries nao muda nada,
porque o loop nunca chega a fazer uma segunda tentativa de verdade.
"""

import random


class TransientNetworkError(Exception):
    pass


def flaky_request(rng):
    """Simula uma chamada de rede que falha de forma transitoria ~70% das vezes."""
    if rng.random() < 0.7:
        raise TransientNetworkError("connection reset by peer")
    return "response-ok"


def fetch_with_retry(max_retries=3, seed=None):
    rng = random.Random(seed)
    last_error = None
    for attempt in range(max_retries):
        try:
            return flaky_request(rng)
        except TransientNetworkError as e:
            last_error = e
            break  # BUG: sai do loop de retry na primeira falha
    raise last_error
