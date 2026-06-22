# 008 — handoff 디자인을 진짜 antd로 이식하는 플레이북 + antd-x v2 함정

날짜: 2026-06-22
맥락: [docs/spec/006](../../docs/spec/006-admin-console-port.md), 회고 [005](../retrospect/005-admin-console-and-playground-port.md)

## 플레이북: claude.ai/design handoff 번들 → 우리 스택(antd 6)
번들의 `_ds_bundle.js`는 antd처럼 보이는 **자체구현 컴포넌트**다. 직접 쓰지 말고 **디자인 명세**로만 보고 진짜 antd로 재현한다(A 방식).

1. **기반을 먼저 안정화한다** (직접): 토큰 CSS(`theme.css`) → 아이콘 레지스트리(`name` 문자열→`@ant-design/icons` 매핑) → mock 데이터(타입 포함) → 공유 컴포넌트(`shared.tsx`). 여기서 **공통 tsc 함정을 선제 차단**한다 — 예: 경량 `DataTable<T>`의 제네릭을 `T extends Record<string,unknown>`로 묶으면 인터페이스 타입을 못 넘김 → 제약 없는 `<T>` + 내부 캐스팅으로.
2. **그다음 뷰를 병렬 서브에이전트로 팬아웃**한다. 각 에이전트에게: 번들 원본 경로 + 기반 API 계약 + 변환 규칙(`window.X`→import, `iconName`→`icon={<Icon/>}`, `prefixIcon`→`prefix`, `Tag color="default"`→색 생략, `RadioGroup`→`Radio.Group` + `onChange e.target.value`)을 명시. 서로 다른 파일이라 충돌 없음. **통합 tsc/build는 내가** 직접.
3. **디자인 개정이 오면 통째로 다시 하지 말고 diff부터.** 기존 번들과 `diff`로 변경된 파일만 식별 → 그 부분만 적용(이번 handoff2는 2파일만 바뀜).

## @ant-design/x v2.8 함정 (런타임/타입)
- **`Bubble.List`/`BubbleList`로 혼합 콘텐츠를 렌더하지 말 것.** 승인 카드·생성형 UI 등 커스텀 메시지가 섞이면 `<div flex column gap>`에 `<Bubble>`/커스텀을 직접 매핑하는 게 안전.
- **`Prompts`**: `items[].icon`은 문자열이 아니라 **ReactNode**, `onItemClick`은 `(info) => info.data`.
- **`Sender`**: `footer`가 노드로 타입 에러 나면 render-prop(`footer={() => ...}`)으로.
- **번들 전용 컴포넌트(`A2UISurface` 등)는 antd-x에 없을 수 있음** → command-stream 해석기를 직접 구현.

## antd Layout 함정
- `Layout.Sider`에 flex를 줘도 antd가 children을 `.ant-layout-sider-children`로 감싸서 안 먹음. **안쪽에 `height:100%; display:flex; flexDirection:column` 한 겹을 더** 둬야 메뉴가 늘어나고 푸터가 바닥에 붙는다.

## 메타
- claude.ai/design 자체에 대한 회의는 **/design-sync(디자인 시스템 동기화)** 에 한정된 것이었고, 그 툴은 우리 레포(디자인 시스템 아님)에 안 맞았다. 반면 **claude.ai/design이 레포를 읽고 만든 handoff 목업**은 레이아웃·컴포넌트·데이터를 구체화해줘서 텍스트 핑퐁보다 UI 구성을 훨씬 쉽게 만들었다 — 도구가 아니라 **용법**이 관건이었다.
