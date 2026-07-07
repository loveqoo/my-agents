/* 스펙 088·207 — assistant 응답 본문 렌더 디스패치.
   렌더러는 @ant-design/x-markdown(XMarkdown) — x 네이티브 AI 마크다운(GFM·수식·DOMPurify·스트리밍
   애니메이션). 스펙 207에서 react-markdown → XMarkdown 교체. 구조(형식 추론·예산 캡·JSON 트리)는 보존.

   - 형식 추론은 스트림 완료(streaming===false)에서만: 부분 버퍼로는 전체-JSON인지
     확정 불가하므로 스트리밍 중엔 항상 markdown 경로(부분 JSON은 트리로 깜빡이지 않음).
   - 보안(스펙 207 관문 — 현 방어 전부 보존):
     · escapeRawHtml: 원문 raw HTML을 평문 이스케이프(현 react-markdown "raw HTML 미렌더" posture 유지).
     · DOMPurify(XMarkdown 내장) — 스크립트·이벤트핸들러·위험 URL 차단.
     · img는 components.img=SafeImgX로 링크 치환 — <img>가 DOM에 안 뜨므로 원격 fetch 미발생
       (codex F3: 비신뢰 LLM 출력의 원격 이미지 추적픽셀이 admin IP/referrer를 흘리는 것 차단).
   - 거대 입력은 parse도 markdown 파싱도 메인스레드를 막으므로(codex F1) 어떤 형식
     추론보다 먼저 렌더 예산을 검사해 원문 캡 블록으로 직행 — 가드를 비용 지점 앞에 둔다.
   - 스트리밍: XMarkdown streaming으로 tail 커서 `▋`·블록 fade-in(스펙 207 사용자 결정). */
import XMarkdown from '@ant-design/x-markdown'
import type { ComponentProps } from '@ant-design/x-markdown'
import '@ant-design/x-markdown/dist/x-markdown.css'
import { detectFormat, jsonTooBigForTree, exceedsRenderBudget } from './messageFormat'
import { JsonTree } from './JsonTree'
import './messageContent.css'

// 트리/마크다운 대신 원문을 그대로 보여주는 폴백(거대·정밀도위험 JSON, 예산 초과 입력).
// 메가바이트 단일 텍스트 노드도 과하므로 표시 길이를 캡하되, 캡했음을 정직히 알린다
// (잘렸으면 "원문 보존"이라 말하지 않는다 — 표시 한도 초과로 일부 생략).
const RAW_DISPLAY_MAX = 20_000

function RawTextBlock({ text }: { text: string }) {
  const clipped = text.length > RAW_DISPLAY_MAX
  const shown = clipped ? text.slice(0, RAW_DISPLAY_MAX) : text
  return (
    <div className="md-body">
      <pre>
        {shown}
        {clipped ? `\n…(표시 한도 초과 — 뒤 ${text.length - RAW_DISPLAY_MAX}자 생략)` : ''}
      </pre>
    </div>
  )
}

// img 자동 로드 차단: XMarkdown ComponentProps의 domNode.attribs에서 src/alt를 읽어 링크로 치환
// (원격 fetch 미발생). src가 없거나 문자열이 아니면 링크 대신 평문(빈 href 링크 방지).
// XMarkdown이 components.img로 이 컴포넌트를 대체하므로 실제 <img>는 렌더되지 않는다.
function SafeImgX({ domNode }: ComponentProps) {
  const attribs = (domNode as { attribs?: Record<string, string> }).attribs ?? {}
  const src = typeof attribs.src === 'string' ? attribs.src : ''
  const alt = typeof attribs.alt === 'string' ? attribs.alt : ''
  const label = alt.length > 0 ? alt : src || '(image)'
  if (src === '') return <span>🖼 {label}</span>
  return (
    <a href={src} title={src} target="_blank" rel="noreferrer noopener nofollow">
      🖼 {label}
    </a>
  )
}

export function MessageContent({ text, streaming }: { text: string; streaming: boolean }) {
  // 예산 초과: parse·markdown 어느 경로든 비싸므로 형식 추론 전에 원문 캡으로 직행.
  if (exceedsRenderBudget(text)) return <RawTextBlock text={text} />
  if (!streaming) {
    const fmt = detectFormat(text)
    if (fmt.kind === 'json') {
      if (jsonTooBigForTree(text)) return <RawTextBlock text={text} />
      return <JsonTree value={fmt.value} />
    }
  }
  return (
    <div className="md-body">
      <XMarkdown
        content={text}
        escapeRawHtml
        components={{ img: SafeImgX }}
        streaming={{ hasNextChunk: streaming, enableAnimation: true, tail: streaming }}
      />
    </div>
  )
}
