# 060 — RAG retrieval 시험 수단: 공유 코어 추출 + 신뢰경계 리셋 (스펙 072)

## 무엇을 했나
사용자 보고: "rag는 등록만 있지 테스트 방법이 없어. 에이전트 설정에 rag 설정 기능이 필요할까?"

먼저 **추측 대신 현 상태를 측정**했다(probe-deeper). 결과 두 갈래:
- (Q1) 에이전트별 RAG 연결은 **이미 있다**(config `vectorTables` + AgentsView "지식 소스" 체크박스, 스펙 037).
  → 신규 기능 불요. 사용자의 "설정 기능이 필요할까?"에 "이미 됨"으로 답.
- (Q2) **진짜 공백**은 retrieval을 *직접* 시험할 길이 없는 것. 지금은 ① 에이전트 채팅 전체(무겁고 간접),
  ② Python 테스트에서 `build_rag_tool` import(사용자 접근 불가)뿐. → AskUserQuestion으로 범위 합의:
  "엔드포인트 + 관리 UI 패널".

구현: P1 공유 코어 `search_collections`(구조화 hit 반환) 추출 → P2 `POST /collections/{cid}/search` →
P3 CollectionsView "검색 시험" 드로어. 검증 3-rung(단위 32건 / 라이브 통합 / 적대 codex) + 037 회귀 + 브라우저.

## 무엇이 잘 됐나
- **drift-방지가 설계의 린치핀이었다.** `build_rag_tool`은 *문자열*을 반환하는데 UI 테이블엔 구조화 데이터가
  필요했다. 평행 검색을 새로 짰다면 "엔드포인트는 초록인데 에이전트 채팅은 다름"이 됐다. 대신 retrieval
  본체를 `search_collections`(구조화 리스트)로 떼고 **양쪽이 호출** — 도구는 그 위 얇은 포맷터로 축소.
  codex가 이를 직접 확인: "build_rag_tool은 *실제로* search_collections를 호출, 평행 분기 없음."
  → learning 075로 일반화(formatter-only 경로에 새 표면 얹기 = 구조화 코어를 양쪽이 공유).
- **거동 보존을 회귀로 증명.** `verify_037`을 손대지 않고 그대로 그린 → 리팩터가 도구 문자열·calls_sink를
  바꾸지 않았다는 직접 증거(058의 "구 라이브 재사용 = 행동등가 증명"과 같은 수법).
- **mock-embed 결정성 트릭 재사용.** 저장 청크와 동일 텍스트 질의 → 거리 0 → 유사도 1.000 → 무조건 rank1.
  mock 시맨틱과 무관하게 정렬·rank 불변식을 단언 가능(037에서 가져옴).

## 무엇이 아팠나 / 교정
- **적대 codex가 신뢰경계 리셋을 짚었다(P2×2).** 내부 도구였던 retrieval을 직접 POST 엔드포인트로 승격하니,
  전엔 LLM/상류가 암묵 제한하던 입력이 이제 **raw로 도착**한다:
  - #1 query 길이 상한 부재 — 거대 query로 임베딩 provider 60초 점유·메모리 점유. → `max_length=4000`.
  - #2 컬렉션 참조 모델이 나중에 chat kind로 바뀌면(PUT update_model 허용) 완전성 검사가 base_url/model_id만
    봐서 502로 뭉개짐. → 엔드포인트에 `em.kind != "embedding"` 가드 → 명확한 400.
  둘 다 **테스트로 봉인**(B6: >4000→422·=4000→200, B7: 모델 kind→chat 후 검색→400). 이게 learning 075의 씨앗.
- **whitespace query가 422 아닌 502로 샜다(자가 발견).** Pydantic `min_length=1`은 strip 전 길이를 봐서
  "   "(3자)가 스키마 통과 후 코어에서 실패 → 502. `@field_validator`로 strip 후 blank면 ValueError(→422).
  교훈: 길이 검증과 의미(비공백) 검증은 다른 층 — min_length만으론 공백을 못 막는다.
- **P3(top_k echo)은 수용.** 스키마 `le=10`이라 실버그 없음(큰 값 422), results 길이가 실건수. 과교정 대신
  정직히 스펙에 기록(faithful-reporting).

## 다음에 적용할 것
- 내부 도구/함수를 외부 엔드포인트로 *승격*할 땐, 상류가 대신 막아주던 입력 제약(길이·종류·존재)을
  **새 입구에서 재검증**한다 → learning 075.
- 단일 표면(문자열 포맷터)에 둘째 표면(구조화 UI/테스트)을 얹을 땐 **구조화 코어를 먼저 빼고** 기존 표면을
  그 위 포맷터로 축소 — 평행 구현 = drift. 기존 검증(verify_037)이 그대로 그린인지로 거동 보존을 증명.
- 참조 자산: verification-ladder-three-rungs / move-breaks-references / probe-deeper / cap-the-raw-source.
