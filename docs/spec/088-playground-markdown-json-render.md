# 088 — 플레이그라운드 응답 markdown 렌더 + raw-JSON 휴리스틱

> 보고: "플레이그라운드 응답이 markdown을 렌더 못 하고 텍스트 그대로 표시." **scope=프런트만(백엔드/스키마 0)** — 사용자 합의(2026-06-30).
> 관련: spec 005(antd-x 채팅 토대)·006(Playground 이식), learning 008(antd-x v2 함정)·080(antd6 셀렉터 probe), 메모리 [core-is-model-config-and-memory](플레이그라운드=보조도구, 과한 금칠 금지).

## 배경 — 측정한 현황

- **render 지점**: `DebugChat.tsx:783-797` — assistant(ai)·user Bubble 둘 다 `content={m.text}`(평문 string). antd-x `Bubble`은 문자열 content를 텍스트 노드로만 그려 markdown이 평문 노출.
- **타입 메타 부재(측정 완료)**: 스트림 프레임 `{text}`(`chat.py:630`·`:467`)·`MessageOut`·`Message` 모델 어디에도 content-type 필드 없음. 더 결정적으로 **LangGraph 런타임이 모델 출력에 포맷을 안 붙임** → "타입을 받아 렌더러를 고른다"의 *정직한 생산자가 지금 없음*.
- 그래서 타입 메타 파이프라인(stream→schema→model→영속)은 추측값을 스키마 표면까지 늘려 박는 것 → **비목표**. 대신 같은 추측을 **렌더 시점 프런트 휴리스틱**으로 공짜로 한다.

## 무엇을 한다 (scope=프런트만)

### 1. markdown 렌더러 (assistant 응답)

- 의존성 추가: `react-markdown` + `remark-gfm`(표·취소선·task-list — LLM 출력 상용구). **둘 다 admin/package.json에 명시 선언**(antd6/antd-x 전이 의존 `marked`에 기대지 않음 — 전이 의존은 깨지기 쉬움).
- **`rehype-raw` 미추가가 안전 기본값**: react-markdown은 기본적으로 raw HTML을 렌더 안 하고(`<script>`·`<img onerror>`는 이스케이프된 텍스트), 링크 URL의 위험 프로토콜(`javascript:`)을 기본 transform이 차단. LLM 출력을 렌더하는 표면이므로 이 기본값을 *유지*하고 raw HTML을 켜지 않는다.
- `DebugChat.tsx`의 **ai Bubble에만** `contentRender={(t) => <MessageContent text={t} streaming={isStreaming} />}` 적용. **(실측 정정)** antd-x v2.8 prop은 `messageRender`가 아니라 **`contentRender`**(`BubbleProps`에 `messageRender` 없음→tsc 에러로 발견, learning 008 antd-x 함정 결). `contentRender`는 *full content*를 받고, node를 반환하면 타이핑 애니메이션이 꺼지지만 점진 markdown은 `m.text`가 토큰마다 자라며 React 재렌더로 풀린다. **user Bubble은 평문 유지** — 사용자가 *실제로 보낸* 입력은 verbatim으로 보여야(markdown 렌더가 `*foo*`를 이탤릭으로 바꿔 "무엇을 보냈나"를 가리면 안 됨). 이 경계를 스펙에 명시.

### 2. raw-JSON 휴리스틱 (전체가 JSON 문서일 때 — 스트림 완료 시 1회)

새 컴포넌트 `admin/src/playground/MessageContent.tsx`. props: `{ text: string; streaming: boolean }`.

- **형식 추론은 스트림 완료에 게이트(핵심 분별)**: 스트리밍 중엔 형식을 *유추할 수 없다*(끝까지 받아야 전체-JSON인지 확정). 실제 도구들도 형식을 "끝에서 추론"하지 않고 프로토콜이 "블록 경계에서 통보"한다 — 우리는 그 타입 프로토콜이 없으므로(측정: 런타임이 포맷 미부여) **완료 신호(`streaming===false`)에서만** JSON 체크를 1회 돌린다. 스트리밍 중(`streaming===true`)엔 항상 markdown 경로. 부수효과: 부분 버퍼로 트리가 깜빡이며 들락거리는 것 차단.
- **JSON 판별 게이트(거짓양성 차단)**: 정착 후 `text.trim()`이 `{` 또는 `[`로 시작 **AND** `JSON.parse` 성공 **AND** 결과가 object/array일 때만 JSON으로 본다. → assistant가 `42`·`true`·`"hi"`만 답한 경우는 (유효 JSON이어도) **markdown 경로**. "전체 응답이 JSON *문서*"만 잡는 정직한 탐지.
- JSON → **경량 접이식 트리**(외부 의존 0, 작은 재귀 컴포넌트). 노드 확장/축소·타입별 색(string/number/bool/null)·배열/객체 자식 수. 보조도구 비례성상 ~100줄 내 자체 구현(react-json-view 같은 무거운 dep·React18 peer 이슈 회피).
  - *대안(스펙 리뷰서 택1 가능)*: 트리가 과하면 `JSON.stringify(parsed, null, 2)` pretty 블록(monospace+복사)으로 더 단순화. 기본 제안은 트리.
- 비-JSON(또는 스트리밍 중) → `<ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>`.

### 3. `typing`/스트리밍 상호작용 (점진 렌더)

`typing={streaming && isLast}`가 켜지면 messageRender가 *부분 content*를 프레임마다 받는다:
- **markdown은 점진 렌더로 풀린다**(실제 도구와 동일): 부분 markdown은 곱게 degrade. 짧은 디버그 메시지라 프레임 재파싱 수용. 미완 펜스(` ``` ` 홀수)는 표시용 speculative-close(가상 닫음 펜스 append) 옵션으로 보강 — 초기엔 미적용, 글리치 보고 시 추가(YAGNI).
- **JSON은 완료까지 markdown**: §2 게이트로 `streaming===true`면 무조건 markdown 경로 → 정착 시 1회 트리 스왑. 부분 JSON이 트리로 깜빡이지 않음. by-design.
- 완료 판정 배선: `DebugChat`에서 ai Bubble의 `streaming && isLast`를 그대로 `MessageContent`의 `streaming` prop으로 전달(이미 그 값을 계산함 — 추가 상태 0).

## 완료 조건 / 검증

- **단위(pure, Node·dep 0)** `tests/verify_088_*`: JSON 판별 게이트 매트릭스 — `{...}`/`[...]`→JSON, `42`/`true`/`"s"`/`  `/`plain text`/`{ 깨진`→markdown 경로(거짓양성 0). 판별 로직을 순수 모듈로 분리해 단언.
- **브라우저(Playwright, 메모리 [verify-ui-in-browser-proactively]·learning 080 probe)**: 플레이그라운드에서 (양성) markdown 응답이 DOM 요소로 렌더(`**bold**`→`<strong>`, 리스트→`<li>`, 표→`<table>`)되고 평문 `**` 잔존 0, (양성) 전체-JSON 응답이 트리로, (음성) 평문 응답·`42`는 트리 아님. 셀렉터는 antd6 개명 가능성에 probe 우선·0개=측정실패.
- **tsc**: `cd admin && npx tsc --noEmit` 0. **build**: `npm run build`로 신규 dep 해소 확인.
- **적대 타자(codex)**: diff 리뷰 — "마스킹/렌더 경계의 여집합"(거짓양성 JSON·XSS 경로·스트리밍 부분 파싱·user verbatim 경계).

## 비목표

- 타입 메타 파이프라인(stream→schema→model→영속 `contentType` 필드) — 정직한 생산자 부재로 추측값만 운반. 에이전트가 *설정으로* structured-output 모드를 가질 때 재검토.
- user 입력 markdown 렌더(verbatim 유지).
- raw HTML 렌더(`rehype-raw`) — XSS 발판, 안전 기본값 유지.
- 코드 펜스 구문 하이라이트(highlight.js/rehype-highlight) — 번들 비용 대비 폴리시, 후속 후보. 초기엔 monospace 블록.

## 검증 결과 (실측, 검증 사다리 3런)

- **단위(pure, Node 24 타입스트리핑·dep 0)** `tests/verify_088_json_detection.ts` **ALL GREEN**: 판별 게이트 J1–J4(object/array/공백/중첩→json)·M1–M11(42/true/"hi"/null/공백/markdown/깨진json/문장속json/펜스json/꼬리텍스트→markdown)·**T1–T5**(`jsonTooBigForTree`: 평범OK·길이초과·16자리정수·15자리OK·문자열속16자리)·**B1–B4**(`exceedsRenderBudget`: 정상·경계·초과·트리캡<렌더예산).
- **브라우저(Playwright+시스템 Chrome, 하니스 `/_harness_088.html`)** `tests/browser/shot-markdown-088.mjs` **ALL GREEN**: A1–A9(markdown→strong/em/h2/li/table/pre·href보존·literal**잔존0·caret없음)·B1–B4(json→트리caret·키·.md-body아님·표/strong없음)·C1–C2(스트리밍 부분json→markdown)·D1–D2(bare 42→markdown)·**E1–E3**(img→링크치환·자동로드차단·alt노출)·**F1–F3**(bigint→트리아님·pre폴백·정수verbatim)·**G1**(깊은중첩→크래시없이 렌더). 시각 확인 `/tmp/markdown-088.png`.
- **tsc** `cd admin && npx tsc --noEmit` **EXIT 0**. build: 하니스(`_harness_088.html`)는 vite 빌드 입력 아님→prod 번들 비포함(테스트 자산으로 커밋).
- **적대 타자(codex)** 2패스: 1패스 4건 발굴, 수정 후 2패스 F1 covering 확정.

### codex 적대 검토 처분표

| # | 심각도 | 발견 | 처분 | 회귀 가드 |
|---|---|---|---|---|
| F1 | HIGH | 거대 JSON/배열 트리 렌더 → 메인스레드 프리즈. **2패스**: 길이캡이 `JSON.parse` *뒤*라 parse 비용 미차단(가드가 비용지점 뒤=non-covering) | **수정(covering)**: `exceedsRenderBudget`(>1MB)를 `detectFormat`·markdown *앞* 최상단에 둠 → parse·remark 둘 다 건너뛰고 원문 캡 블록. 트리캡(50k)·`CHILD_CAP`(200)도 별개 방어 | 단위 B1–B4(임계·경계·parse전차단), 브라우저 F·G |
| F2 | MED | 깊은 중첩 펼침 → 동기 재귀 콜스택/시간 | **수정**: `MAX_DEPTH=12`에서 재귀 중단 요약 | 브라우저 G1(크래시없음), 코드 상수 |
| F3 | MED | markdown 이미지 자동 로드 → 추적픽셀이 admin IP/referrer 누출(비신뢰 LLM 출력) | **수정**: `SafeImg`로 `<img>`→링크 치환(자동 fetch 0, 클릭은 사용자 의도) | 브라우저 E1–E3 |
| F4 | LOW-MED | `JSON.parse` 16자리+ 정수 정밀도 손실 → 디버그 콘솔이 *틀린 ID* 표시 | **수정**: `/[0-9]{16,}/` 검출 시 트리 대신 원문 verbatim pre(정확 정수 보존) | 단위 T3·T5, 브라우저 F3 |
| nit1 | LOW | `RawJsonBlock` "원문 보존" 문구가 20k truncate와 모순(정직성) | **수정**: 잘리면 "표시 한도 초과 — 뒤 N자 생략"으로 정직 표기 | 코드 |
| nit2 | LOW | `SafeImg` src 없을 때 빈 href→현재 페이지 링크 | **수정**: href 없으면 링크 대신 평문 span | 코드 |

by-design 잔존(codex 정당 인정): `42`/`true`만 답→markdown(전체 JSON *문서*만 트리)·펜스 감싼 JSON은 비-트리(markdown이 그림)·user Bubble verbatim 비대칭(보낸 입력 보존).
