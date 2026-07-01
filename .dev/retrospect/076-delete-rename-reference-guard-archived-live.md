# 076 — 참조 무결성 삭제/rename 가드: "archived는 죽었다"는 미검증 가정이 맹점이었다 (스펙 093)

> 참고 자산: retrospect 036(047 회고 — 셀프 GREEN 뒤 삭제가드 누락 적발), learning 050
> (delete 가드는 형제 연산 안 덮음·operation-symmetry), learning 048(생성 한 시점 보장≠수명 전체),
> learning 069/070(모든 입구·전 수명 커버·covering-guard), spec 062(중앙 error detail 헬퍼).

## 무엇을 했나

MCP 서버·RAG 컬렉션은 에이전트 config에서 **name 문자열**로 참조된다(FK 아님). 삭제/rename하면
config에 dangling name만 남고 런타임이 조용히 도구/RAG 없이 동작한다. 이 실수를 삭제/rename 시점에
**409로 차단**하는 참조 무결성 가드를 넣었다(스펙 093). 검증 사다리 3런 전부 통과(단위 40/0, 실DB
통합 T1–T9, codex 적대 2회).

## 무엇이 잘못됐고 무엇을 배웠나

### 1. 맹점 = "archived 버전은 죽은 이력이라 스캔에서 제외" (codex가 측정으로 반증)

초안 설계는 참조 스캔 범위를 "활성 config + draft 버전"으로 잡고 **archived를 제외**했다. 근거는
"archived는 draft를 거치지 않으면 활성화할 수 없다"는 *가정*이었다. codex 적대리뷰가 이걸 **측정으로
반증**했다 — `activate_version`(`agents.py:225`)은 주석 "archived=롤백은 허용"과 함께 archived 버전을
**명시적으로 active로 승격**하고(`:232`) `agent.config`를 그 config로 부활시킨다(`:235`). 즉 archived
참조는 죽은 이력이 아니라 **롤백 가능한 live 참조**다. archived name을 지우면 롤백 순간 서빙 config에
dead ref가 부활한다.

이건 learning 069/070 covering-guard의 정확한 사례다: "이 상태는 도달 불가"라는 **미검증 수명 가정**이
곧 가드의 구멍이 된다. 스캔을 "활성화 가능한 *모든* 버전"으로 넓혀(archived 포함) 닫았다.

### 2. 삭제만 막으면 rename이 샌다 (operation-symmetry, learning 050)

name 링크를 끊는 입구는 삭제만이 아니다 — MCP rename(`PUT`)도 옛 name을 config에 dangling으로 남긴다.
codex가 형제 입구로 적발. 삭제와 **동일 헬퍼**를 rename 입구에도 걸어(`action="이름 변경"` 인자만
교체) 닫았다. 입구를 닫힌 집합으로 열거(삭제 2 + rename 1)해 세지 않으면 하나가 샌다는 learning 070의
재확인.

### 3. 가드와 런타임이 *같은 normalizer*를 안 쓰면 판정이 어긋난다 (codex P2)

가드는 config를 스캔하고, 런타임(`chat.py`)도 같은 config를 `name.in_(...)`로 해석한다. 이 둘이 참조
판정을 **다르게** 하면(예: dict 모양 config를 런타임은 키로 해석·가드는 무시) 가드가 통과시킨 걸
런타임이 참조로 쓰거나 그 반대가 된다. `config_names` 단일 normalizer(list[str]만 인정)를 **양쪽이
공유**하게 만들어 drift 0으로 닫았다.

### 4. dict detail이 아니라 string detail — 중앙 error 계약 존중 (자기 교정)

초안은 참조 목록을 dict `detail`로 반환하려 했으나, 중앙 error 헬퍼(`httpError.ts`, spec 062)와 뷰들의
기존 409 관례는 **string `detail`만** 추출·노출한다. dict를 주면 프런트가 일반 폴백만 보여 참조 목록이
안 뜬다. 사람이 읽는 문자열로 바꿔 **프런트 변경 0줄**로 기존 `message.error(e.message)` 경로가 그대로
안내를 렌더한다. (읽기 전 코드베이스 관례를 측정해 설계를 코드베이스에 맞춘 사례.)

## 복리 포인트

- **셀프 GREEN이 맹점을 못 잡는다** — 내 단위/통합 테스트는 *내가 상상한 실패*("archived는 제외돼야
  한다")만 확인했다. archived를 제외한 채로도 초록이었다. codex(rung③)가 "보장 목록의 여집합"을
  때려 archived-부활을 짚었다. retrospect 036의 재현: 셀프 GREEN 뒤 가드 누락 — 이번엔 codex가 그
  자리에서 적발. 비가역·파괴 경로는 적대 타자 검증이 필수다.
- **미검증 수명 가정 = 다음 맹점의 씨앗** — "이 상태는 도달 불가"를 코드 측정 없이 단정하면(probe-deeper
  자기주장판) 그게 곧 가드의 구멍이 된다. 상태 전이(activate/rollback)를 실제 코드로 열어 확인해야 한다.
- **TOCTOU는 정직히 이연** — 가드 스캔↔삭제 commit 사이 경쟁(update_agent/activate_version이 name을
  다시 넣는 것)은 서빙 불변식 논증으로 경계를 밝히고 spec 094로 분리했다. 부분 가드를 조용히 출하하지
  않고 잔존을 §5에 호명(retrospect 036 교훈).
