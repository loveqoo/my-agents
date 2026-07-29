"""suite 진행 파일(스펙 431) — 장시간 스위트를 밖에서 보이게(구남님 제안 2026-07-19).

사람 채널(러너의 스트리밍 출력)과 별개로, 기계가 폴링할 수 있는 진행 파일을 원자적으로 갱신한다:
  /tmp/suite-progress.json = {runner, total, done, ok, fail, current, elapsedS, updatedAt}

계약: **실패 무해** — 진행 기록(파일 쓰기)이 어떤 이유로 실패해도 스위트 실행을 절대 못 깬다
(모든 쓰기를 try로 흡수). 원자성=tmp+rename(반쪽 JSON을 읽는 소비자가 없게).
소비자: `cat /tmp/suite-progress.json` 폴링 또는 `watch -n2`. 러너 둘(씨앗 그물 run_suite.py ·
실모델 배터리 suite/run.py)이 이 한 클래스를 공유한다(사본 금지).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime

PROGRESS_PATH = "/tmp/suite-progress.json"


class ProgressWriter:
    """진행 상태 1런 분량 — start(이름)로 '지금 도는 것', finish(이름, ok)로 완료 집계."""

    def __init__(self, runner: str, total: int, path: str = PROGRESS_PATH) -> None:
        self.runner = runner
        self.total = total
        self.path = path
        self.done = 0
        self.ok = 0
        self.fail = 0
        self.current = ""
        self._t0 = time.monotonic()
        self._write()

    def start(self, name: str) -> None:
        """직렬 구간용 — 지금 도는 테스트를 표시(병렬 구간은 finish만 써도 충분)."""
        self.current = name
        self._write()

    def finish(self, name: str, ok: bool) -> None:
        self.done += 1
        if ok:
            self.ok += 1
        else:
            self.fail += 1
        self.current = name
        self._write()

    def _write(self) -> None:
        try:
            payload = {
                "runner": self.runner,
                "total": self.total,
                "done": self.done,
                "ok": self.ok,
                "fail": self.fail,
                "current": self.current,
                "elapsedS": round(time.monotonic() - self._t0, 1),
                "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:  # noqa: S110 — 계약: 진행 기록 실패가 스위트를 못 깬다
            pass
