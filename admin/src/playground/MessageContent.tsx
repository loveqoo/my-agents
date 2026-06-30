/* 스펙 088 — assistant 응답 본문 렌더 디스패치.
   - 형식 추론은 스트림 완료(streaming===false)에서만: 부분 버퍼로는 전체-JSON인지
     확정 불가하므로 스트리밍 중엔 항상 markdown 경로(부분 JSON은 트리로 깜빡이지 않음).
   - 보안: react-markdown 기본값 유지(raw HTML 미렌더·위험 URL 차단) — rehype-raw 미추가.
     추가로 img는 자동 로드를 막고 링크로 치환(codex F3: 비신뢰 LLM 출력의 원격 이미지가
     추적 픽셀이 되어 admin IP/referrer를 외부로 흘리는 것 차단 — 클릭은 사용자 의도).
   - 거대 입력은 parse도 markdown 파싱도 메인스레드를 막으므로(codex F1) 어떤 형식
     추론보다 먼저 렌더 예산을 검사해 원문 캡 블록으로 직행 — 가드를 비용 지점 앞에 둔다. */
import type { ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
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

// img 자동 로드 차단: alt(없으면 src)를 노출하는 일반 링크로 치환(원격 fetch 미발생).
// src가 없거나 문자열이 아니면 링크 대신 평문(현재 페이지로 가는 빈 href 링크 방지).
function SafeImg({ src, alt }: ComponentPropsWithoutRef<'img'>) {
  const href = typeof src === 'string' ? src : ''
  const label = alt && alt.length > 0 ? alt : href || '(image)'
  if (href === '') return <span>🖼 {label}</span>
  return (
    <a href={href} title={href} target="_blank" rel="noreferrer noopener nofollow">
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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: SafeImg }}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
