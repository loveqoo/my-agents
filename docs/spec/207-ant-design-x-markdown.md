# 207 — ant-design-x 생태계 채택(x-markdown) + 204 보류 정리

## 배경 (사용자 "ant-design/x 레포에 다양한 기능 소개" → "@ant-design/x-markdown 안 쓰나요?")
채팅은 이미 `@ant-design/x`의 `Bubble`·`Sender`·`Prompts`를 쓴다. 그러나 메시지 본문 렌더러
(`MessageContent`)는 `react-markdown`으로 직접 만들었다. 조사 결과 **`@ant-design/x-markdown@2.8.0`**
(x와 동일 버전)이 실재한다 — GFM(marked)·수식(katex)·**DOMPurify 살균**·AI 스트리밍 애니메이션
(tail `▋`·fade-in·미완성 마크다운 로딩)까지 갖춘 **x 네이티브 AI 마크다운 렌더러**. "x에 마크다운 없음"은
오판이었다(사용자 교정). npm description이 "placeholder"라 오해했으나 실 dist 5.8MB로 실물 확인.

## 왜 채택하나 (그냥 x-native라서가 아니라)
- **AI 스트리밍 UX**: tail 커서·블록 fade-in·미완성 링크/이미지 로딩 — 토큰 스트림에 맞게 설계됨.
- **수식(katex)**: LLM 답변의 수식 렌더(현 react-markdown엔 없음).
- **x 일관성**: `Bubble`과 같은 생태계 — 규칙(모든 UI antd/x)과 정합.

## 관문: 보안 보존 (현 MessageContent가 codex 지적으로 심은 방어를 잃지 않는다)
현 `MessageContent`의 방어를 **전부 보존**해야 채택이 회귀가 아니다:
1. **원격 img 자동로드 차단**(codex F3 — 비신뢰 LLM 출력의 추적픽셀이 admin IP/referrer 유출): 현
   `components={{ img: SafeImg }}`가 img를 링크로 치환. → XMarkdown도 `components?: {[tag]: Comp}`
   노출(interface.d.ts:119). **단 props 형태가 다름**: react-markdown `{src,alt}` → XMarkdown
   `ComponentProps`(html-react-parser `domNode`.attribs 기반). SafeImg를 그 형태로 재작성.
2. **XSS 살균**: XMarkdown 내장 DOMPurify + `dompurifyConfig?`(interface.d.ts:168)로 강화 가능.
3. **렌더 예산 캡**(codex F1 — 거대 입력이 메인스레드 블록): `exceedsRenderBudget` 가드는 **XMarkdown
   호출 앞단**에 그대로(비용 지점 앞 가드). 초과 시 RawTextBlock 직행 — 렌더러 무관하게 유지.
4. **JSON→트리 분기**: `detectFormat`→`JsonTree`는 앱 고유 기능, 렌더러 무관하게 유지.

## 설계
### A. 의존성
- `admin/package.json`에 `@ant-design/x-markdown@2.8.0` 추가(x 버전 고정). x-markdown CSS import.
- react-markdown/remark-gfm는 MessageContent가 유일 소비처면 제거(측정 후). 아니면 유지.

### B. MessageContent 재작성 (구조 보존, 렌더러만 교체)
```
if (exceedsRenderBudget(text)) return <RawTextBlock/>      // ① 캡 — 그대로
if (!streaming) { const fmt = detectFormat(text)
  if (fmt.kind==='json') { if(jsonTooBigForTree) return Raw; return <JsonTree/> } }  // ④ 그대로
return <XMarkdown content={text} components={{img: SafeImgX}}
         dompurifyConfig={{...}} streaming={{ hasNextChunk: streaming, ... }}/>  // ②③ 보존+스트리밍
```
- `SafeImgX`: XMarkdown ComponentProps에서 `domNode.attribs.src/alt` 읽어 링크 치환(현 SafeImg 로직 이식).
- 스트리밍: `streaming` prop을 XMarkdown `StreamingOption.hasNextChunk`로 연결(완료 시 flush).
  **tail 커서 `▋`·블록 fade-in 적극 도입**(사용자 결정 2026-07-07): `enableAnimation:true`+`tail:true`,
  미완성 링크/이미지 loading 매핑. AI 타이핑 느낌 강화.

### C. 204 보류 5건 정리(이 스펙에 흡수)
- ② MessageContent → **x-markdown 채택**(위 A·B). JsonTree = x/antd 대응물 없음 → **유지**(예외 명시).
- ① TrendChart SVG = 차트, x에 없음(별개 @ant-design/plots) → **유지**(예외 명시).
- ③ DataTable 모바일 카드 = flex+Panel(=Card). **antd List가 v6 deprecated**(제거 예정)라 List로
  안 옮김 — Flex 프리미티브 위 Card 조립이 규칙 부합이자 미래지향 → **현행 유지**(주석 명시).
- ④ InlineFormPanel·ArtifactCard = raw `<div>` 카드 → **antd `Card`로 교체**(완료, tsc0).
- ⑤ 죽은 `components/Chat.tsx`(아무도 import 안 함) → **삭제**(완료).

### D. admin/CLAUDE.md 예외 목록
"antd/x 대응물 없어 커스텀 유지" 목록 명문화: JsonTree(JSON 트리 뷰어), TrendChart(스파크라인 —
차트는 @ant-design/plots 도입 시 재검토). 규칙과 모순 없게 근거 기록.

## 검증 (자가검증 지양 — 타자·측정)
1. **보안 적대 검증(codex 또는 실측 e2e)**: (a) 원격 img 마크다운 → 네트워크 요청 **미발생**(추적픽셀
   차단 유지) — read_network_requests로 img 도메인 요청 0건 단언. (b) `<script>`·onerror 등 XSS
   페이로드 → 미실행. (c) 거대 입력(>예산) → RawTextBlock 직행(메인스레드 캡 유지).
2. **렌더 무회귀 스샷**: shot-markdown-088(코드블록·표·링크·목록) + 신규 수식 케이스 · 플레이그라운드
   ④ 폼(asking)·산출물(done) 카드 육안.
3. **스트리밍**: 실모델 턴에서 토큰 스트림 중 부분 마크다운이 깨지지 않고(미완성 링크/이미지 loading)
   완료 시 정상 flush.
4. tsc0 · ui-audit 3종.

## 검증 결과 (2026-07-07)
- **shot-markdown-088 하네스 24/24 GREEN**(실 MessageContent 마운트): A1~A9 마크다운(굵게·기울임·
  제목·목록·표·코드펜스·링크 href 보존)·B1~B4 JSON 트리 분기·C1~C2 스트리밍 마크다운·D1~D2 bare
  스칼라·**E1 <img> 미렌더(원격 자동로드 차단)·E2 src 링크 href 보존·E3 alt 노출**·F1~F3 예산/bigint
  폴백·G1 깊은 중첩. → 3방어(추적픽셀·XSS raw HTML·예산 캡)+JSON 트리 전부 보존 확인.
- **육안 스샷**(/tmp/markdown-088.png): 스타일 이중적용 없음·스트리밍 tail 커서 `▋` 표시·이미지=
  "🖼 추적픽셀" 링크 치환.
- **codex 적대 검증**(여집합 공격): **G1(원격 fetch)·G2(XSS) 방어 유지 확인** — video poster·svg
  image href·style url()·link preload·picture srcset·div background-image·raw `<img>` 전부 escapeRawHtml로
  평문화, 마크다운 img(참조형 포함)는 components.img=SafeImgX로 `<a>` 치환(fetch 0), `javascript:` URL은
  DOMPurify가 살균. **G3(예산 캡) 우회 1건 발견(High)→수리**: 바이트캡(1MB) 아래 GFM 표/목록이 DOM
  요소로 폭증(`"|"+"x|"*240000`≈960KB→`<th>` 24만·HTML 2.6MB 프리즈). → messageFormat에 **구조 증폭
  대리값**(파이프·줄바꿈 가중 renderCost) 추가해 함께 캡. 단위 B5~B8(표/목록 캡·코드블록 과캡 방지) 추가.
- react-markdown/remark-gfm = MessageContent가 유일 실소비처였음(harness 언급은 낡은 주석) → **제거 완료**.

## 경계
- tail 애니메이션/커서 **적극 도입**(사용자 결정) — 단 접근성(prefers-reduced-motion) 존중은 챙김.
- @ant-design/plots(차트) 도입은 OUT(별건 — TrendChart 유지, 예외 기록만).
- antd v6 광범위 deprecation(List·Drawer width·Alert message) 전면 마이그레이션은 OUT → 백로그 별건.
