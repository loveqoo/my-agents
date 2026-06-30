/* 스펙 088 브라우저 검증용 임시 하니스(커밋 안 함). 실제 MessageContent +
   JsonTree + react-markdown + theme.css를 픽스처로 마운트해 렌더를 단언한다. */
import { createRoot } from 'react-dom/client'
import '../theme.css'
import { MessageContent } from './MessageContent'

const MD = [
  '## 제목입니다',
  '',
  '**굵게** 그리고 *기울임*, 그리고 `inline code`.',
  '',
  '- 항목 A',
  '- 항목 B',
  '',
  '| 열1 | 열2 |',
  '|-----|-----|',
  '| a   | b   |',
  '',
  '```js',
  'const x = 1',
  '```',
  '',
  '> 인용문',
  '',
  '[링크](https://example.com)',
].join('\n')

const JSON_DOC = JSON.stringify({
  name: 'agent',
  tools: ['rag', 'mcp'],
  config: { temp: 0.7, nested: { deep: true, n: 42, z: null } },
})

// F3: markdown 이미지 — 자동 로드 차단(링크 치환) 검증용.
const MD_IMG = '응답에 이미지가 있습니다:\n\n![추적픽셀](http://evil.example/pixel.gif)'

// F4: 16자리+ 정수 → 트리 대신 원문 pre 폴백(정밀도 보존) 검증용.
const JSON_BIGINT = '{"id":9007199254740993,"name":"x"}'

// F2: MAX_DEPTH(12) 초과로 깊은 중첩 → 깊이 상한에서 재귀 중단(요약) 검증용.
let deep: unknown = 'bottom'
for (let i = 0; i < 20; i++) deep = { next: deep }
const JSON_DEEP = JSON.stringify(deep)

function Block({ id, label, text, streaming }: { id: string; label: string; text: string; streaming: boolean }) {
  return (
    <div data-testid={id} style={{ margin: 16, padding: 12, border: '1px solid #ddd', maxWidth: 680 }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{label}</div>
      <MessageContent text={text} streaming={streaming} />
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <div>
    <Block id="md" label="markdown (settled)" text={MD} streaming={false} />
    <Block id="json" label="json doc (settled)" text={JSON_DOC} streaming={false} />
    <Block id="json-streaming" label="partial json while streaming → markdown" text={'{"partial":'} streaming={true} />
    <Block id="num" label="bare 42 (settled) → markdown" text={'42'} streaming={false} />
    <Block id="md-img" label="markdown image → 링크 치환(자동로드 차단)" text={MD_IMG} streaming={false} />
    <Block id="json-bigint" label="16자리+ 정수 → 원문 pre 폴백(정밀도 보존)" text={JSON_BIGINT} streaming={false} />
    <Block id="json-deep" label="깊은 중첩 → 크래시 없이 렌더(MAX_DEPTH 가드)" text={JSON_DEEP} streaming={false} />
  </div>,
)
