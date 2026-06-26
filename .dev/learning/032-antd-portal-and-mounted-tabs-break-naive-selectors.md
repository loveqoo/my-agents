# 032 — antd의 포털 렌더·전체 마운트가 단순 브라우저 셀렉터를 깨뜨린다

맥락: 스펙 030 `MemoryView`(Tabs + Select) Playwright 검증. 컴포넌트는 멀쩡히 렌더됐는데
하니스가 옵션 선택·필터 입력을 못 해 두 번 헛돌았다.

## 두 함정

1. **Select 옵션은 포털에 렌더된다.** `<Select>`의 드롭다운 항목은 셀렉터 인라인이 아니라
   `document.body`의 `.ant-select-dropdown`(포털)에 그려진다. placeholder/셀렉터 텍스트를
   클릭한다고 옵션이 잡히지 않는다. **확실한 길**: 셀렉터를 클릭해 열고 → (showSearch면)
   검색어를 타이핑해 거른 뒤 → `.ant-select-item-option`(포털 내)을 클릭.
2. **Tabs는 비활성 탭도 마운트한다.** antd `Tabs`는 기본적으로 모든 탭 패널을 DOM에 두고
   비활성 패널을 `display:none`으로 숨긴다(`destroyInactiveTabPane`을 켜지 않는 한). 같은
   placeholder의 인풋이 탭마다 있으면 `getByPlaceholder(...).first()`가 **숨은** 탭의 것을
   잡아 `fill`이 "element is not visible"로 타임아웃한다. **해결**: `.locator('visible=true')`
   또는 활성 탭 패널 스코프 안에서 찾기.

## 왜 중요한가 (복리)

"컴포넌트가 안 보인다 → 버그"로 오판하기 쉽다. 실제론 **제품은 정상, 하니스 가정이 틀린**
경우다. [[probe-deeper-before-concluding]]의 UI 판: 화면이 비면 내 셀렉터부터 의심하라.
이 레포는 [[verify-ui-in-browser-proactively]]로 브라우저 검증을 반복하므로, antd를 쓰는 한
이 두 가정(포털·전체 마운트)은 매번 적용된다.

## 적용점

- antd UI 하니스는 옵션을 **포털**에서, 입력을 **visible 스코프**에서 찾는다.
- `tests/browser/shot-memory-view.mjs`의 `pick()`/필터 셀렉터가 레퍼런스 구현.
- 다른 프로젝트라도 포털 기반 드롭다운(Radix/MUI/antd)·항상 마운트 탭이면 동일 패턴.
