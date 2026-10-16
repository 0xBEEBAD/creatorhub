"""Account-level operation journal shared by API and background workers."""
from __future__ import annotations

from .db import get_session
from .event_center import emit_event
from .models import AccountOperationLog


def record_account_operation(*, platform: str, account_id: int,
                             task_type: str, task_id, action: str,
                             status: str, target: str = "", channel: str = "",
                             risk_signal: str = "", detail: str = "",
                             duration_ms: int = 0) -> int:
    with get_session() as session:
        row = AccountOperationLog(
            platform=platform, account_id=account_id,
            task_type=task_type, task_id=str(task_id or ""), action=action,
            target=str(target or "")[:500], channel=str(channel or "")[:100],
            status=status, risk_signal=str(risk_signal or "")[:160],
            detail=str(detail or "")[:3000], duration_ms=max(0, int(duration_ms or 0)),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        row_id = int(row.id)
    emit_event(
        "account.operation",
        {"operation_id": row_id, "platform": platform, "account_id": account_id,
         "task_type": task_type, "task_id": str(task_id or ""), "action": action,
         "status": status, "target": str(target or ""),
         "risk_signal": str(risk_signal or ""), "detail": str(detail or "")},
        aggregate_type="account", aggregate_id=str(account_id),
    )
    return row_id
