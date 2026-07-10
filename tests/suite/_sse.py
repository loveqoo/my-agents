"""SSE 응답 파서 — chat.py 스트림 계약(스펙 288 스위트 공용).

프레임: 첫 {"session": id} → {"text": chunk}* → ({"approval": {...}} | {"artifact": ...})?
→ 최종 `event: trace` + `event: done`. 단언은 최종 trace 프레임에서만(기록 기반 원칙).
"""

from __future__ import annotations

import json
from typing import Any


def parse_sse(body: str) -> dict[str, Any]:
    """SSE 본문 전체를 프레임별로 해석해 {session, text, trace, approval, artifact}로 접는다."""
    out: dict[str, Any] = {"session": None, "text": "", "trace": None, "approval": None, "artifact": None, "error": None}
    # CRLF 정규화(codex 288 #3) — SSE 표준은 \r\n도 허용. \n만 가정하면 프레임이 안 갈라져
    # trace를 놓치고, 부재(absence) 단언들이 공허하게 통과한다.
    body = body.replace("\r\n", "\n")
    for block in body.split("\n\n"):
        event = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
        if not data_lines:
            continue
        raw = "\n".join(data_lines)
        if event == "trace":
            out["trace"] = json.loads(raw)
            continue
        if event == "done":
            continue
        try:
            j = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(j, dict):
            continue
        if "session" in j:
            out["session"] = j["session"]
        if "text" in j and isinstance(j["text"], str):
            out["text"] += j["text"]
        if "approval" in j:
            out["approval"] = j["approval"]
        if "artifact" in j:
            out["artifact"] = j["artifact"]
        if "error" in j:
            out["error"] = j["error"]
    return out
