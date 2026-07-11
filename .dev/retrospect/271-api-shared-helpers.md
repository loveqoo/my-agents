# 271 — api 공통 헬퍼 정본화 (스펙 296)

## 무엇을 했나

스펙 295(agent flow)에 이어 api 쪽 중복 4종을 정본화:
- **A2A JSON-RPC 프레이밍** → `a2a_wire.py` 신설. mock_remote·a2a_server의 로컬 클로저
  `_a2a_user_text`/`_response`/`_status_event`/`_error`(rpc_id·task_id 캡처)를 모듈 함수
  `a2a_user_text`/`a2a_result`/`a2a_error`/`a2a_status_event`로 — 캡처 변수를 인자로 뽑아 단일화.
- `_card_streaming` → `a2a_client.card_streaming`(chat_stream·broker agent provider 공유).
- `_assert_valid_name` → `naming.assert_valid_name`(blocks·agents/crud 공유).
- `_non_blank` 두 validator → `schemas._require_non_blank`(`field_validator("query")` 공유).

수치: 로컬 def/클로저 0·정본 각 1·`make metrics-fast`(ruff/mypy 0)·verify_042(44)·117·148 + 스위트
51/51·codex 5항목(4 SAFE + 1 정직화). get-or-404(36곳)는 소유권 경계라 스펙 297로 분리.

## 잘된 것

- **클로저 캡처를 인자로 뽑아 서버 2벌을 합쳤다.** A2A 프레임의 rpc_id/task_id는 각 핸들러의
  지역 클로저가 캡처하던 값 — 모듈 함수 인자로 승격하니 mock_remote(개발용)와 a2a_server(실서버)가
  **같은 wire 포맷 정본**을 쓴다. mock↔실서버 드리프트가 구조적으로 불가능해짐(공유가 곧 계약).
- **dedup이 죽은 재수출을 드러냈다.** `agents/__init__`이 `validate_resource_name`·`_assert_valid_name`을
  import하는데 본문서 안 쓰고 외부 참조도 0이었다(스펙 291 분할 때 쓸어담은 재수출 잔재). 중복 정리가
  아니었으면 안 보였을 죽은 코드 — 정본화의 부수 청소.
- **codex의 CONFIRMED를 "정직화"로 판정했다(결함 아님).** codex가 "chat/broker 파사드에서
  `_card_streaming` 제거 = 재수출 계약 breaking"을 CONFIRMED로 짚었다. 그러나 전 저장소 grep으로
  **실 importer 0·파사드 vars() 스냅샷 테스트 부재**를 확인 — 이건 *심볼 소실*이 아니라 *심볼 이전*
  (private `_card_streaming` → public `a2a_client.card_streaming`). 재수출 규약의 목적(기존 import 경로
  불파괴)은 아무도 그 경로를 안 써 충족된다. 죽은 재수출을 되살리는 게 아니라 관계를 정직 기록하는 게 맞다.

## 배운 것

- **"파사드에서 심볼을 뺐다"는 재수출 계약 변경이 맞지만, 결함 여부는 importer·스냅샷으로 갈린다.**
  *이전(relocation)*과 *소실(loss)*은 다르다 — 심볼이 제 집으로 옮겨가고 옛 경로를 아무도 안 쓰면
  안전한 이전이다. 판별은 자가선언 아닌 **측정**(전 저장소 importer grep + 스냅샷 테스트 유무).
  [[complement-attack-can-be-honest-boundary]]의 재수출판 — 적대 지적이 항상 코드결함은 아니다.
- **재수출 심볼을 옮길 땐 그 심볼을 재노출하던 파사드 줄도 함께 갱신해야 한다.** mypy가 잡았다
  (`chat._card_streaming` attr-defined) — 파사드 재수출은 정적으로 검증되는 계약이라 mypy가 그물.
  헬퍼 이동 = ①정의 이동 ②호출부 교체 ③**파사드 재수출 갱신** 3박자.
- **공유가 곧 드리프트 방지다(개발 mock ↔ 실서버).** mock_remote가 개발용이어도 A2A wire를 실서버와
  공유하면 "mock만 포맷이 어긋나 통합 테스트가 거짓 초록"을 원천 차단. 중복 제거의 이득은 줄 수보다
  **계약 단일화**.

## 다음에 적용

- **스펙 297 = get-or-404(36곳)**: `session.get(Model,id)`+404를 `db.get_or_404`로. 단 소유권-스코프
  fetch(SELECT-WHERE·조인)는 **제외**(순수 PK-get만) — RBAC 체크리스트·codex 적대 동반(404 fold·존재
  비노출 불변식 보존).
- authz `_own_scope`/`_is_admin`(라우터 독립 저자 의도)·eval_* 중복은 별도 판단.
- 낡은 verify_084(fake `A` .source 누락)는 pristine HEAD 동일 실패 — 무관, 백로그.
