# 095 — name 기반(비-FK) 참조 가드는 *링크를 끊는 모든 연산* × *활성화 가능한 모든 상태*를 덮고 런타임과 normalizer를 공유해야 한다

**맥락**: 자원(MCP 서버·RAG 컬렉션)을 에이전트 config가 **name 문자열**로 참조(FK 아님)할 때, 삭제/
rename로 config에 dangling name이 남아 런타임이 조용히 그 능력 없이 동작하는 걸 막는 참조 무결성 가드를
설계·구현할 때(스펙 093).

## 규칙 — 세 축을 동시에 덮어야 가드가 샌다

1. **연산 축(operation-symmetry, learning 050):** name 링크를 끊는 입구는 **삭제만이 아니다** —
   **rename도** 옛 name을 dangling으로 남긴다. 링크를 끊는 *모든* 입구를 닫힌 집합으로 열거하고
   (삭제 + rename + 일괄/cascade가 있으면 그것도) **동일 헬퍼**를 건다(`action` 인자만 교체).

2. **상태 축(covering-guard, learning 069/070 + 048):** 참조 스캔 범위는 "지금 서빙 중인 config"만이
   아니라 **활성화 가능한 모든 버전**이다. 특히 **"archived는 죽은 이력이라 제외"는 미검증 가정**일 수
   있다 — 상태 전이 코드를 **측정**하라. `activate_version`이 archived 롤백을 허용하면 archived 참조는
   *롤백 순간 서빙 config에 부활하는 live 참조*다. "이 상태는 도달 불가"를 코드로 열어 확인하지 않으면
   그 가정이 곧 가드의 구멍이 된다.

3. **정합 축(guard/runtime drift):** 가드가 "참조다"라고 판정하는 기준과 런타임(`name.in_(...)`)이
   해석하는 기준이 **같은 normalizer**를 공유해야 한다. 다르면(예: dict 모양 config를 런타임은 키로
   해석·가드는 무시) 가드 통과분을 런타임이 참조로 쓰거나 그 반대가 된다. list[str]만 인정하는 단일
   `config_names`를 양쪽이 import해 drift 0.

## 왜 (근본 원인)

셋의 공통 뿌리는 **"참조는 한 곳·한 연산·한 시점에만 있다"는 암묵 축소**다. name 참조는 FK가 아니라
DB가 무결성을 안 지켜주므로, *애플리케이션이* 참조가 살 수 있는 **전 표면**(연산×상태×해석)을 세야
한다. 하나라도 빠지면 happy-path 테스트는 초록이지만(내가 상상한 경로만 검사) 빠진 표면으로 dead ref가
샌다.

## 어떻게 적용

- **입구를 닫힌 집합으로 grep**: 자원 name을 바꾸거나 지우는 라우트를 전수 열거(삭제·rename·일괄).
  seed/cascade가 *생성*만인지 *삭제/개명*도 하는지 확인.
- **상태 전이 코드를 측정**: `activate_version` 류가 어떤 상태(draft/archived)를 서빙으로 승격하는지
  주석·라인으로 확인. "도달 불가"를 단정 말고 열어보라(probe-deeper).
- **normalizer 하나로 통일**: 가드와 런타임이 같은 함수로 config[field]→name 리스트를 뽑게. 비정상
  모양(dict/스칼라/비-str)은 양쪽 모두 fail-safe로 접기.
- **적대 타자 검증(rung③)**: 셀프 GREEN은 상상한 실패만 본다. 비가역·파괴 경로는 codex에 "보장 목록의
  *여집합*"을 시켜라 — archived-부활·rename-형제·타입-불일치를 이번에 codex가 전부 짚었다.
- **잔존 정직히 호명**: 스냅샷 가드로 못 막는 TOCTOU(스캔↔commit 사이 재삽입)는 서빙 불변식 논증으로
  경계를 밝히고 후속 스펙으로 분리. 부분 가드를 조용히 출하 금지(retrospect 036).

관련: [[operation-symmetry]] learning 050, covering-guard learning 069/070, learning 048(생성 한
시점 보장≠수명 전체), retrospect 076(이 스펙의 회고).
