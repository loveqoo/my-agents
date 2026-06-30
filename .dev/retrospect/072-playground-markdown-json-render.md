# 072 — 플레이그라운드 응답 markdown 렌더 + raw-JSON 휴리스틱

스펙: `docs/spec/088-playground-markdown-json-render.md`
관련 learning: 091(이번), [[installed-guard-isnt-covering-guard]]=082, [[cap-the-raw-source-not-the-buffer]]=059,
[[core-is-model-config-and-memory]], [[adversarial-review-before-destructive-ship]], [[probe-deeper-before-concluding]],
[[verification-ladder-three-rungs]], learning 008(antd-x v2 함정)
선행: spec 005(antd-x 채팅 토대)·006(Playground 이식)

## 무엇을 했나

플레이그라운드가 assistant 응답을 평문 string으로만 그려 markdown이 안 풀리던 걸, ai Bubble에만
`react-markdown`+`remark-gfm`를 물리고, *전체가 JSON 문서*인 응답은 경량 접이식 트리로 그렸다.
scope=프런트만(백엔드/스키마 0, 사용자 합의). 핵심 설계는 **타입 메타 파이프라인이 아니라 렌더시점
휴리스틱**(learning 091 사실2).

## 무엇이 어긋났고 무엇을 배웠나

### 1. 사용자의 "타입 정보를 받을 수 있다면"을 액면 수용하지 않고 생산자를 실측했다

원 보고가 "이런 타입 정보를 받을 수 있다면 렌더러도 바꿀 수 있겠다"였다. 솔깃한 방향(스트림·스키마에
contentType 추가)이지만, 실측하니 **LangGraph 런타임이 포맷을 안 붙인다** — 정직한 생산자가 없다.
추측값을 스키마 표면까지 늘려 박는 대신 같은 추측을 렌더시점에 공짜로 했다. 보조도구에 스키마 확장은
[[core-is-model-config-and-memory]]가 경계하는 과투자.

### 2. "스트리밍이라 끝까지 받아야 형식 유추 가능"을 다른 도구가 어떻게 푸는지로 재구성했다

사용자가 정확히 짚었다: "스트리밍으로 렌더하는데 끝까지 받아야 형식을 유추할 텐데 다른 곳은 어떻게
해결하지?" 답: 실제 도구는 *끝에서 추론 안 한다* — 프로토콜이 블록 경계에서 타입을 *통보*한다. 우리는
그 프로토콜이 없으니 차선책으로 **완료 게이트**(`streaming===false`에서만 JSON 1회), 스트리밍 중엔
곱게 degrade하는 markdown. 추가 상태 0(`streaming && isLast` 재사용).

### 3. antd-x prop을 추측하다 tsc로 정정했다 (learning 008 결)

`messageRender`로 썼다가 tsc가 "`BubbleProps`에 없음"으로 떨궜다. 설치본 `interface.d.ts`를 실측하니
**`contentRender`**가 맞고, full content를 받으며 node 반환 시 타이핑 애니메이션이 꺼진다(점진 markdown은
`m.text`가 자라며 React 재렌더로). 추측 대신 설치본 타입을 읽는 게 learning 008의 antd-x 함정 교훈.

### 4. codex 적대 리뷰가 covering의 *순서* 축을 가르쳤다 — F1 (핵심)

자가 검증(단위+브라우저+시각+tsc)이 전부 초록인데 codex가 4건을 짚었다. 그중 F1이 날카로웠다:
내 길이캡(`jsonTooBigForTree`)이 `detectFormat`의 `JSON.parse` *뒤*에 있어, 거대 JSON의 parse 비용은
가드 앞에서 이미 지불된다 — **가드 검사지점이 비용지점보다 뒤=non-covering**([[installed-guard-isnt-covering-guard]]의
시간 축). 처음 나는 "트리 렌더 프리즈는 막았으니 닫혔다"고 볼 뻔했다([[probe-deeper-before-concluding]]).
수정: `exceedsRenderBudget`(>1MB)를 `detectFormat`·markdown *둘 다보다 앞* 최상단에 둬 parse·remark를
모두 건너뛰게 하고, *순서 자체*를 단언하는 단위 핀(B1–B4)을 박았다. 2패스 codex가 CLOSED 확정.

F2(깊은 중첩→`MAX_DEPTH`)·F3(markdown 이미지 자동로드 추적픽셀→링크 치환)·F4(16자리 정수 정밀도→원문
pre)도 넷 다 싸서 고쳤다. 보조 표시 도구라도 1–3줄 covering 가드는 "과한 금칠"이 아니다 — 금칠 회피는
*비쌀 때* 적용. nit 2건(truncate해놓고 "원문 보존"이라 한 문구·빈 href 링크)도 정정.

### 5. 하니스를 던지지 않고 테스트 자산으로 남겼다

브라우저 회귀(`shot-markdown-088.mjs`)가 `/_harness_088.html`에 의존하므로 하니스를 *재현 가능 자산*으로
커밋했다(vite 빌드 입력 아님→prod 번들 비포함). 검증을 던지면 다음 회귀를 못 잡는다.

## 핵심 한 줄

"타입을 받아 렌더러를 고른다"는 정직한 생산자가 있을 때만 파이프라인이고, 없으면 렌더시점 휴리스틱+완료
게이트로 공짜로 한다. 그리고 가드는 *설치*가 아니라 *덮음*이며 덮음은 범위뿐 아니라 **순서**다 — 비싼
연산을 막는 가드는 그 연산 앞에 있어야 한다(codex가 길이캡이 parse 뒤임을 짚어 가르침).
