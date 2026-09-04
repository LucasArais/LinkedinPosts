"""
Embeddings locais (sentence-transformers), sem depender de API externa
para a parte de retrieval - a Anthropic API e usada so pelas chamadas de
LLM (agente e recorder), nao para embeddings, que ela nao oferece
nativamente. Modelo pequeno (~80MB, baixado uma vez e cacheado
localmente) e suficiente para comparar frases curtas de task_signature e
approach.
"""

import numpy as np

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed(text: str) -> np.ndarray:
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Assume que a e b ja vieram normalizados de `embed` (norma 1)."""
    return float(np.dot(a, b))
