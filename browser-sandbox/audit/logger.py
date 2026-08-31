"""
Logger de auditoria JSONL append-only para o browser sandbox. Mesmo
principio do guarded-agent (linha por evento, timestamp, decisao com
motivo) mas com o vocabulario de eventos de um browser: navigate, click,
type, read_page, screenshot, download, e as decisoes que os bloqueiam.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class AuditLogger:
    def __init__(self, log_path: Path, session_id: str):
        self.log_path = Path(log_path)
        self.session_id = session_id
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> dict:
        full_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            **record,
        }
        line = json.dumps(full_record, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return full_record

    def log_action(self, step: int, action: str, args: dict) -> dict:
        return self._write({"step": step, "type": "action", "action": action, "args": args})

    def log_decision(
        self, step: int, action: str, args: dict, decision: str, reason: str
    ) -> dict:
        return self._write(
            {
                "step": step,
                "type": "decision",
                "action": action,
                "args": args,
                "decision": decision,
                "reason": reason,
            }
        )

    def log_result(self, step: int, action: str, result: Any, error: Optional[str] = None) -> dict:
        return self._write({"step": step, "type": "result", "action": action, "result": result, "error": error})

    def log_session_end(self, step: int, status: str, summary: str = "") -> dict:
        return self._write({"step": step, "type": "session_end", "status": status, "summary": summary})
