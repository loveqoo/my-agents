# 090 — 분리된 표면에선 위협 모델을 *실측*하라(상속한 심각도 의심)·표시 redactor가 영속 경로를 깰 수 있다

선행 리뷰(086)가 "P0 비밀누출"으로 짚어 별 스펙(087)으로 분리해둔 보안 항목을 실행할 때, 그리고
사람에게 보일 데이터를 정화(redact)하는 함수가 그 정화된 값을 *영속 저장소*(JSONB·DB)에도 싣는
경로를 가질 때.

## 두 축

### A. 상속한 심각도를 의심하고 *분리된 표면에서* 위협 모델을 재실측하라

리뷰가 결함을 발견한 *맥락*에서 매긴 심각도(P0)는, 그 결함을 분리해 단독으로 보면 달라질 수 있다.
086 노드 summary 표면 옆에서 본 MCP args 누출은 P0로 *보였지만*, 087로 분리해 단독 위협 모델을
실측하니 **defense-in-depth 갭**으로 내려갔다:

- **시스템 자기 비밀이 그 표면에 실제로 도달하는가?** grep/read로 확인 — MCP Bearer는 연결 *헤더*,
  모델 api_key는 클라이언트 *설정*이라 도구 kwargs/result에 안 온다. "노출될 수 있는 데이터"와
  "노출되는 *우리* 비밀"은 다르다.
- **표면의 인증 경계는?** admin/owner 전용이면 "공개 누출"이 아니라 "인증된 자가 자기 데이터 봄".

심각도를 상속하면 (1)과투자(보조도구에 086급 full allowlist=과한 금칠)하거나 (2)사용자가
"왜 하는지 모르겠다"로 근거를 *먼저* 치게 된다. probe-deeper는 단정 전에도 적용되지만 *상속받은
근거*에도 적용된다 — 액면 수용 말고 분리 표면에서 직접 측정. **등급이 내려가도 0은 아니다**: 싸고
정직한 최소 처방(scope B)으로 닫되, 표면의 *목적*이 처방 polarity를 정한다(보여주는 게 목적인 args는
키 blocklist+값 보존, 임의 내부 상태는 값 allowlist — 089와 정당하게 반대).

### B. 표시용 redactor라도 *영속 경로*를 깰 수 있다(JSONB NaN/Infinity)

같은 정화 함수의 출력이 화면 렌더뿐 아니라 DB(`Approval.args` JSONB)에도 영속될 때, redactor는
**유효한 직렬화 형태**를 보장해야 한다. float를 원문 통과시키면 `NaN`/`Infinity`가 끼어 JSONB·엄격
JSON(`json.dumps(allow_nan=False)`)에 비유효 → commit이 깨진다. **보안 표시 기능이 영속성을 깬다**는,
"비밀 가리기"만 보면 안 떠오르는 *측면 효과* 축이다. 처방: redactor를 fail-closed로 — 비유한 float는
`<nan>` 안전 마커, 미지 타입은 타입명만, 비문자 키는 `str(k)`, 깊이 상한+try/except. 검증은
`json.dumps(allow_nan=False)`로 *출력의 직렬화 가능성 자체*를 단언(값만 보지 말고 형태를 단언).

## 검증

- 위협 모델 실측은 코드로: 의심되는 비밀의 *실제 거주지*를 grep/read로 확정(헤더 vs kwargs).
- redactor 출력은 `json.dumps(allow_nan=False)` 통과를 단언(JSONB 호환=영속 안전).
- 키 패턴 확장(F1 `*_key`)은 거짓양성 회귀핀 동반(monkey/top_k는 구분자 없어 안 걸림을 단언).
- 적대자에게 "마스킹 말고 *영속/직렬화*를 깰 입력은?"도 시켜라(F2는 누출 아닌 깨짐 축).

## 공명

[[probe-deeper-before-concluding]](상속 근거에도 적용)·089(값 allowlist — 087은 목적상 반대
polarity의 형제)·[[cap-the-raw-source-not-the-buffer]]=059(result 캡)·중앙 경계(끝단 N 말고 원천
runtime.py)·[[adversarial-review-before-destructive-ship]](여집합에 *깨짐* 축 포함)·과한 금칠 회피
(보조도구는 토대만큼 안 조임)

[inherited-severity,reframe-on-isolated-surface,threat-model-measure-not-assume,defense-in-depth-vs-p0,display-redactor-breaks-persistence,jsonb-nan-infinity,failclosed-serialization,assert-serializable,purpose-sets-polarity,probe-deeper,adversarial-codex]
