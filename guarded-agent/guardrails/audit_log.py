"""
Logger de auditoria: toda decisao da camada de guardrails (e todo pensamento/
chamada/resultado do agente) e escrita como uma linha JSON em um arquivo
JSONL, com timestamp. O formato append-only e uma linha por evento facilita
revisar depois com `jq`, grep, ou carregar em um dataframe.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class AuditLogger:
    def __init__(self, log_path: Path, session_id: str, task_id: str):
        self.log_path = Path(log_path)
        self.session_id = session_id
        self.task_id = task_id
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> dict:
        full_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "task_id": self.task_id,
            **record,
        }
        line = json.dumps(full_record, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return full_record

    def log_thought(self, step: int, text: str) -> dict:
        return self._write({"step": step, "type": "thought", "text": text})

    def log_tool_call(self, step: int, tool_name: str, tool_args: dict) -> dict:
        return self._write(
            {"step": step, "type": "tool_call", "tool_name": tool_name, "tool_args": tool_args}
        )

    def log_decision(
        self, step: int, tool_name: str, tool_args: dict, decision: str, reason: str
    ) -> dict:
        return self._write(
            {
                "step": step,
                "type": "decision",
                "tool_name": tool_name,
                "tool_args": tool_args,
                "decision": decision,
                "reason": reason,
            }
        )

    def log_tool_result(
        self, step: int, tool_name: str, result: Any, error: Optional[str] = None
    ) -> dict:
        return self._write(
            {"step": step, "type": "tool_result", "tool_name": tool_name, "result": result, "error": error}
        )

    def log_session_end(self, step: int, status: str, summary: str = "") -> dict:
        return self._write({"step": step, "type": "session_end", "status": status, "summary": summary})
