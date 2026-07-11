# 296 — api 공통 헬퍼 정본화: A2A 프레이밍·카드 스트리밍·이름검증·공백검증

## 배경

스펙 295 후속 — 넓힌 중복 전수(retrospect 270)의 B 중 **안전한 소형 4건**(api). get-or-404(36곳)는
소유권·404 fold 경계라 RBAC 체크리스트 대상 → **스펙 297로 분리**. authz `_own_scope`/`_is_admin`은
저자 의도(라우터 독립)라 별도 판단.

**측정된 중복(본문 diff 근거):**
- **B2 A2A JSON-RPC 프레이밍**: `mock_remote.py` ↔ `a2a_server.py`에 `_a2a_user_text`(바이트 동일)·
  `_response`(rpc_id 캡처 클로저, 동일)·`_status_event`(task_id 캡처 클로저, 동일) 3함수 복제 +
  a2a_server의 `_error`·릴레이 루프 인라인 error dict.
- **B5 `_card_streaming`**: `chat_stream.py` ↔ `broker/providers/agent.py` 바이트 동일(도크스트링이
  "순환 import 피해 로컬 복제"라 자백).
- **B6 `_assert_valid_name`**: `blocks.py` ↔ `agents/helpers.py` 바이트 동일(둘 다 `validate_resource_name`+400).
- **B7 `_non_blank`**: `schemas.py` 두 validator(CollectionSearchIn·MemorySearchIn) 동일.

## 목표 (측정 가능)

1. **B2 → `a2a_wire.py` 신설**: 모듈 함수로 클로저 캡처를 인자화 —
   - `a2a_user_text(params) -> str`, `a2a_result(rpc_id, result) -> dict`,
     `a2a_error(rpc_id, code, message) -> dict`, `a2a_status_event(rpc_id, task_id, text, *, final, state) -> str`.
   - mock_remote·a2a_server의 로컬 `_a2a_user_text`/`_response`/`_status_event`/`_error` 삭제·정본 호출.
   - 측정: 두 파일에서 `def _a2a_user_text`·`def _response`·`def _status_event`·`def _error` = **0**.
2. **B5 → `a2a_client.py`에 `card_streaming(card) -> bool`**: chat_stream·agent provider 로컬 복제 삭제.
   순환 확인(a2a_client는 chat/broker 미의존). 측정: `def _card_streaming` = **0**.
3. **B6 → `naming.py`에 `assert_valid_name(name) -> None`**: blocks·agents/helpers 로컬 복제 삭제.
   측정: `def _assert_valid_name` = **0**(둘 다 naming.assert_valid_name 호출).
4. **B7 → schemas 모듈 함수 `_require_non_blank(v) -> str`**: 두 validator가 `field_validator("query")
   (_require_non_blank)`로 공유. 측정: 중복 본문 1개로.
5. **행위 보존(바이트 동일)**: A2A 프레임 wire 포맷·카드 스트리밍 판정·400/422 거부가 정확 동일.
   verify_042(a2a_client)·117(a2a 협업)·148(이름)·084(메모리검색)·관련 스위트 + `make metrics-fast`.

## 설계

### a2a_wire.py
```python
def a2a_user_text(params: dict) -> str:  # message.parts[].text(kind=="text") join
def a2a_result(rpc_id, result: dict) -> dict:  # {"jsonrpc":"2.0","id":rpc_id,"result":result}
def a2a_error(rpc_id, code: int, message: str) -> dict:  # {...,"error":{"code","message"}}
def a2a_status_event(rpc_id, task_id, text: str, *, final: bool, state: str) -> str:
    # status-update SSE 프레임: f"data: {json.dumps(a2a_result(rpc_id, {...}), ensure_ascii=False)}\n\n"
```
호출부: mock_remote·a2a_server의 클로저를 모듈 함수 호출로(rpc_id/task_id를 인자로). a2a_server의
릴레이 루프 error·`_error`도 `a2a_error(rpc_id, ...)`로. wire 포맷 문자열 정확 보존.

### card_streaming (a2a_client.py) / assert_valid_name (naming.py)
로컬 def를 정본으로 올리고 이름만 공개(`_`→공개). 본문 무변경. import 교체.

### _require_non_blank (schemas.py)
```python
def _require_non_blank(v: str) -> str:
    s = v.strip()
    if not s:
        raise ValueError("질의는 공백일 수 없습니다.")
    return s
```
각 클래스: `_non_blank = field_validator("query")(_require_non_blank)`. min_length strip-전 함정 주석은
정본 함수에 1회 보존.

## 검증
- 행위 보존: verify_042·117(A2A)·148(이름 규칙)·084(메모리 검색 공백 거부) + 스위트 51/51.
- 수치: 각 로컬 def 0(grep)·정본 각 1·`make metrics-fast`(ruff/mypy 0)·import 스모크.
- 적대(codex): A2A wire 포맷 바이트 동일·클로저→인자 캡처값(rpc_id/task_id) 정합·422/400 거부 보존.

## OUT
- **get-or-404(36곳) = 스펙 297**(소유권·404 fold·SELECT-WHERE 경계 — 순수 PK-get만 대상, 적대 검증 동반).
- authz `_own_scope`/`_is_admin`(라우터 독립 저자 의도 — 설계 판단 별도).
- eval_* 계열 중복(미전수 — 별도 조사).
- mock_remote는 개발용이나 A2A wire는 실서버와 동일 계약 → 공유가 드리프트 방지(정당).
