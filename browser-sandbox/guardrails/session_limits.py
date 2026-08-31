"""
Limites de sessao: numero de paginas navegadas e tempo total decorrido.
Recebe o relogio de fora (`now_fn`) para ser testavel sem `time.sleep` de
verdade - os testes da Camada 1 simulam o avanco do tempo diretamente.
"""

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SessionLimits:
    max_pages: int = 20
    max_duration_seconds: float = 300.0


@dataclass
class SessionLimiter:
    limits: SessionLimits
    now_fn: Callable[[], float] = field(default=time.monotonic)
    pages_visited: int = field(default=0, init=False)
    _started_at: float = field(default=0.0, init=False)
    _started: bool = field(default=False, init=False)

    def start(self) -> None:
        self._started_at = self.now_fn()
        self._started = True
        self.pages_visited = 0

    def record_page_visit(self) -> None:
        if not self._started:
            self.start()
        self.pages_visited += 1

    def elapsed_seconds(self) -> float:
        if not self._started:
            return 0.0
        return self.now_fn() - self._started_at

    def pages_exceeded(self) -> bool:
        return self.pages_visited > self.limits.max_pages

    def time_exceeded(self) -> bool:
        return self._started and self.elapsed_seconds() > self.limits.max_duration_seconds

    def is_expired(self) -> bool:
        return self.pages_exceeded() or self.time_exceeded()

    def expiry_reason(self) -> str:
        if self.pages_exceeded():
            return f"Limite de {self.limits.max_pages} paginas por sessao excedido ({self.pages_visited} visitadas)"
        if self.time_exceeded():
            return (
                f"Limite de {self.limits.max_duration_seconds}s por sessao excedido "
                f"({self.elapsed_seconds():.1f}s decorridos)"
            )
        return ""
