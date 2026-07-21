# 339 — 모델 튜닝 파라미터 N-확장 단일화(스펙 411)

## 발단
개발자 "모델 메타값 오버라이드가 아직 부자연스럽다. 두 개 영역만 만들고 N개로 확장 못 함. 온도·반복
패널티 같은 튜닝값을 관리·오버라이드할 방법이 필요하다." → 409가 stream/thinking 2개만·temperature는
별도 특례라 **3중 불균일**이었다.

## 무엇을 했나
409 서술자 패턴을 **숫자 파라미터까지 일반화**. `ParamDescriptor`(kind bool/number·wire top/
extra_body/disable_streaming·range)로 stream·enable_thinking·temperature·top_p·max_tokens·
repetition_penalty를 한 목록(PARAMS)에. build_chat_openai가 wire별 배선(top=ChatOpenAI kwargs,
extra_body=비표준), 캐스케이드(모델→에이전트→노드→세션) 대상 확장, temperature 흡수(스펙 077 은퇴),
UI는 kind별 렌더(bool 3상·number InputNumber) 한 컴포넌트 4화면.

## 배운 것 (복리 후크)

- **일반화의 완성은 특례 흡수** — repetition_penalty·top_p를 추가하는 것보다 **temperature를 흡수**하는
  게 핵심이었다(특례가 하나라도 남으면 "N개로 확장" 실패). 흡수는 배선(loader fold·serializer fold·
  override 통일·ctx 파생)을 여러 곳 건드려 위험하지만, 남기면 사용자가 계속 "불균일"을 본다. **기존
  특례를 은퇴시키는 게 새 축 추가보다 어렵고 중요**([[extend-generic-not-parallel-hardcode]]의 다음 단계).

- **흡수 시 "정본은 하나"를 저장·직렬화·폼·실행 전부에서** (codex P2) — 실행부만 modelParams로 접으면
  저장/API에코/폼은 여전히 이중 노출("어느 쪽이 이기나?"의 답이 층마다 다름). serializer가 접고
  필드를 None으로 노출해야 폼이 한 곳에서 로드. 마이그레이션은 로드(_fold_temperature)+직렬화 양쪽.

- **병합 시점이 우선순위**(codex P1, 회고 337 재확인) — 레거시 세션 temperature 키를 하위호환으로
  남겼더니 저장 modelParams가 setdefault로 세션값을 이겼다("세션 최상위" 위반). FE를 새 경로로
  바꿨으면 **옛 경로를 은퇴**시켜야(안 그러면 두 경로가 순서로 충돌). [[merge-order-is-priority]].

- **UI 일반화는 캐스케이드 전 층에 표면** — 노드형 플그 세션 modelParams 표면을 빠뜨려 4층 계약이
  UI에서 회귀(codex P1②). 백엔드가 층을 구현하면 **각 층마다 편집 표면**이 있어야 계약이 산다.
  [[context-control-propagates-to-affordances]].

- **유한수 경계**(codex P2) — number 파라미터는 NaN/Infinity를 거부해야(int() 예외·무의미 클램프).
  bool 배제 + math.isfinite. 공유 정리기의 장점은 한 곳 수정이 전부에 적용, 단점은 공유 사각지대.

## 검증
verify_411 24/24(서술자 파생·유효값·클램프·wire 배선·temperature 흡수·캐스케이드·세션>저장·유한수)·
verify_409 21/21(411 계약 현행화)·모델폼 파라미터 UI 브라우저 확인(Temperature·Top P·최대 토큰·반복
패널티 InputNumber)·FE 빌드·codex 2패스. **P4 UI는 fast-worker 위임**(6파일 변환, tsc 0 측정 마감) —
설계는 메인이 정의·검증. 그물 잔여 red(124/130/131/158)는 선재 환경 플레이크(fresh-DB 하네스 백로그).
