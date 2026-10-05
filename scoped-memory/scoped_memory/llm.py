"""
Cliente de LLM minimo: OpenRouter via endpoint compativel com a API da
OpenAI (SDK `openai` direto, sem framework de agente).

O Orchestrator so conhece a interface `LLM.complete(system, messages)`,
o que permite trocar por um FakeLLM nos testes - o teste de vazamento de
sessao inspeciona exatamente o que seria enviado ao modelo.

Modelos `:free` do OpenRouter tem dois problemas praticos: rate limit
upstream frequente (429) e, por serem modelos de raciocinio, as vezes
gastam todo o max_tokens pensando e devolvem `content` vazio. Por isso o
cliente pede raciocinio em esforco baixo e, em qualquer um dos dois
casos, cai para o proximo modelo da lista de fallback.
"""

import time
from typing import Dict, List, Optional, Protocol

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLM(Protocol):
    def complete(self, system: str, messages: List[Dict[str, str]], max_tokens: int = 800) -> str: ...


class OpenRouterLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: Optional[List[str]] = None,
        base_url: str = OPENROUTER_BASE_URL,
        rounds: int = 2,
    ):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=90)
        self.models = [model] + [m for m in (fallback_models or []) if m and m != model]
        self.rounds = rounds

    def complete(self, system: str, messages: List[Dict[str, str]], max_tokens: int = 800) -> str:
        from openai import APIStatusError, APITimeoutError

        last_error: Optional[str] = None
        for round_ in range(self.rounds):
            if round_:
                time.sleep(3)
            for model in self.models:
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        # raciocinio conta no max_tokens: folga pra sobrar resposta
                        max_tokens=max_tokens + 3000,
                        messages=[{"role": "system", "content": system}] + messages,
                        extra_body={"reasoning": {"effort": "low", "exclude": True}},
                    )
                except (APIStatusError, APITimeoutError) as exc:
                    last_error = f"{model}: {exc.__class__.__name__}"
                    continue
                content = (response.choices[0].message.content or "").strip() if response.choices else ""
                if content:
                    return content
                last_error = f"{model}: resposta vazia"
        raise RuntimeError(f"nenhum modelo respondeu ({last_error})")
