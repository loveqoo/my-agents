"""A2A JSON-RPC 응답 프레이밍 정본(스펙 296) — mock_remote·a2a_server 공유.

서버 응답 봉투(result/error)·status-update 스트림 프레임·요청 텍스트 파싱을 한 곳에. 이전엔 두 서버가
rpc_id/task_id를 캡처하는 로컬 클로저로 복제했다 — 캡처 변수를 인자로 뽑아 단일화(mock↔실서버 wire
포맷 드리프트 방지). 순수 함수(외부 의존 없음).
"""

from __future__ import annotations

import json
from typing import Any


def a2a_user_text(params: dict) -> str:
    """JSON-RPC params.message.parts[].text(kind=='text')를 모아 잇는다(a2a_client 송신과 동형)."""
    msg = (params or {}).get("message") or {}
    parts = msg.get("parts") or []
    out = []
    for part in parts:
        if isinstance(part, dict) and part.get("kind") == "text" and part.get("text"):
            out.append(str(part["text"]))
    return "".join(out)


def a2a_result(rpc_id: Any, result: dict) -> dict:
    """JSON-RPC 성공 응답 봉투."""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def a2a_error(rpc_id: Any, code: int, message: str) -> dict:
    """JSON-RPC 에러 응답 봉투."""
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def a2a_status_event(rpc_id: Any, task_id: str, text: str, *, final: bool, state: str) -> str:
    """status-update SSE 프레임(message/stream) — 텍스트 청크를 agent 메시지로 감싼다."""
    result = {
        "kind": "status-update",
        "taskId": task_id,
        "status": {
            "state": state,
            "message": {
                "role": "agent",
                "parts": [{"kind": "text", "text": text}],
                "kind": "message",
            },
        },
        "final": final,
    }
    return f"data: {json.dumps(a2a_result(rpc_id, result), ensure_ascii=False)}\n\n"
