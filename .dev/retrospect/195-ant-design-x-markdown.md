# 195 — ant-design-x 채택(x-markdown): 내 오판을 사용자가 두 번 교정, codex가 예산 우회를 잡음

## 맥락
스펙 204 보류 5건을 정리하려던 차, 사용자가 "ant-design/x 레포에 다양한 기능 소개"를 짚고, 이어
"@ant-design/x-markdown 안 쓰나요?"라 물었다. 나는 처음에 "x에 마크다운 렌더러 없음 → MessageContent
유지"라 단정했다. **둘 다 오판이었고, 사용자가 밀어붙여 교정됐다.**

## 무엇이 잘못됐나 (내 단정 2연)
1. **"x에 마크다운 없음"** — 사실은 `@ant-design/x-markdown@2.8.0`이 x와 동일 버전으로 실재한다
   (GFM·katex·DOMPurify·스트리밍 애니메이션). 내가 채팅용 x 컴포넌트(Bubble/Sender)만 보고 별도
   마크다운 패키지를 안 찾았다.
2. **npm description="placeholder"에 또 속을 뻔** — 게시본 설명이 "placeholder for
   @ant-design/x-markdown"이라 "이름 선점용"으로 판단할 뻔했으나, `npm pack`으로 dist 5.8MB 실물
   (XMarkdown 컴포넌트·latex·애니메이션)을 확인해 뒤집었다. **설명 필드가 실물을 숨긴다** — 내용물을
   봐야 안다([[probe-deeper-before-concluding]]의 재확인: 내 측정이 사용자 보고와 어긋나면 측정을 의심).

## 무엇을 배웠나
- **채택은 "x-native라서"가 아니라 "대응물이 실제로 있고, 우리 방어를 보존할 수 있어서"**. XMarkdown이
  `components={{img}}`(HTML 요소 커스텀 렌더러)와 `dompurifyConfig`·`escapeRawHtml`을 노출해서,
  현 MessageContent의 3방어(추적픽셀 img 차단·XSS·raw HTML 미렌더)를 **전부 이식 가능**했다. props
  형태만 다름(react-markdown `{src,alt}` → XMarkdown `ComponentProps.domNode.attribs`).
- **가장 좋은 커스텀 잔재 처리는 삭제가 아니라 "권장 통합점 확인"일 수 있다** — MessageContent는
  버릴 커스텀이 아니라, 알고 보니 Bubble의 `contentRender`/x-markdown `components` 권장 패턴이었다.

## codex가 잡은 것 (자가검증이 못 본 여집합)
shot-markdown-088 하네스 24/24는 **내가 상상한 실패**(표준 img·js URL)만 봤다. codex 적대검증이
**바이트캡 아래 구조 증폭**을 잡았다: `exceedsRenderBudget`가 `text.length>1MB`만 봐서,
`"|"+"x|".repeat(240000)`(≈960KB, 캡 통과)이 `<th>` 24만 개·HTML 2.6MB로 메인스레드를 프리즈.
이건 **react-markdown 시절부터 있던 선재 결함**(캡이 raw 길이만 봄)이지만, 내가 "예산 캡 유지"를
주장하며 이 코드를 건드리니 지금 고치는 게 맞았다. → messageFormat에 구조 증폭 대리값(파이프·줄바꿈
가중 `renderCost`) 추가, 단위 B5~B8로 회귀 고정(표/목록 캡 + 코드블록 과캡 방지 핀 함께).
[[cap-the-raw-source-not-the-buffer]]의 확장: 캡은 raw에서 걸되 **바이트가 아니라 요소 비용**으로.
G1(원격fetch: video/svg/style/link/picture/css-url·raw img 다각 시도 전부 escapeRawHtml 평문화)·
G2(XSS: js URL DOMPurify 살균)는 codex도 못 뚫어 방어 유지 확인.

## 부수 결정
- ③ 모바일 카드를 List로 옮기려다 **`antd List`가 v6에서 deprecated**(콘솔 경고)임을 발견 → 되돌려
  Flex+Card 유지(deprecated로 이동은 역방향). admin/CLAUDE.md 예외 목록 + `.dev/backlog.md`에 v6
  deprecation 전면 마이그레이션(List·Drawer width·Alert message) 별건 기록.

## 다음에 적용
- 라이브러리 "없다" 단정 전에 **동일 org의 자매 패키지**를 찾는다(x → x-markdown). npm description이
  아니라 `npm pack` 내용물로 실물 판정.
- 렌더러 교체 같은 보안 민감 변경은 **하네스 초록으로 끝내지 말고 codex 여집합**(다른 fetch 벡터·구조
  증폭·DoS)을 반드시 태운다([[verification-ladder-three-rungs]]의 적대 rung).
