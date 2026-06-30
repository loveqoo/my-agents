/* 스펙 088 — 경량 접이식 JSON 트리(외부 의존 0). assistant 응답 전체가 JSON
   문서일 때 markdown 대신 이걸로 그린다. 색은 src/theme.css의 팔레트 CSS 변수
   사용(타입별: string=green / number=geekblue / bool=gold / null=tertiary). */
import { useState } from 'react'

const MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"
const PAD = 14
// codex F2: 사용자가 깊은 체인을 계속 펼치면 동기 재귀 렌더가 콜스택/시간을 먹는다.
// 이 깊이 이상은 재귀를 멈추고 요약만 — 길이캡(jsonTooBigForTree)과 함께 렌더 폭주를 막는다.
const MAX_DEPTH = 12
// 한 노드의 자식 표시 상한: 50k 캡을 통과해도 작은 노드가 수천 개면 비싸므로 슬라이스.
const CHILD_CAP = 200

function Caret({ state }: { state: 'open' | 'closed' | 'none' }) {
  return (
    <span style={{ display: 'inline-block', width: '1.1em', color: 'var(--color-text-tertiary)' }}>
      {state === 'open' ? '▾' : state === 'closed' ? '▸' : ''}
    </span>
  )
}

function Punc({ t }: { t: string }) {
  return <span style={{ color: 'var(--color-text-tertiary)' }}>{t}</span>
}

function Prim({ v }: { v: unknown }) {
  if (v === null) return <span style={{ color: 'var(--color-text-tertiary)' }}>null</span>
  if (typeof v === 'string') return <span style={{ color: 'var(--green-7)' }}>{JSON.stringify(v)}</span>
  if (typeof v === 'number') return <span style={{ color: 'var(--geekblue-7)' }}>{String(v)}</span>
  if (typeof v === 'boolean') return <span style={{ color: 'var(--gold-7)' }}>{String(v)}</span>
  return <span>{String(v)}</span>
}

function Node({ keyName, value, isLast, depth }: { keyName?: string; value: unknown; isLast: boolean; depth: number }) {
  // 상위 2계층은 펼쳐 보여 디버그 가치 확보, 그보다 깊으면 접어 거대 JSON 관리.
  const [open, setOpen] = useState(depth < 2)
  const isObj = value !== null && typeof value === 'object'
  const comma = isLast ? '' : ','
  const keyEl =
    keyName !== undefined ? (
      <>
        <span style={{ color: 'var(--color-text)' }}>{JSON.stringify(keyName)}</span>
        <Punc t=": " />
      </>
    ) : null

  if (!isObj) {
    return (
      <div style={{ paddingLeft: depth * PAD }}>
        <Caret state="none" />
        {keyEl}
        <Prim v={value} />
        <Punc t={comma} />
      </div>
    )
  }

  const isArr = Array.isArray(value)
  const entries: Array<readonly [string | undefined, unknown]> = isArr
    ? (value as unknown[]).map((v) => [undefined, v] as const)
    : Object.entries(value as Record<string, unknown>)
  const ob = isArr ? '[' : '{'
  const cb = isArr ? ']' : '}'
  const n = entries.length

  if (n === 0) {
    return (
      <div style={{ paddingLeft: depth * PAD }}>
        <Caret state="none" />
        {keyEl}
        <Punc t={ob + cb + comma} />
      </div>
    )
  }

  // 깊이 상한 도달: 더 내려가지 않고 한 줄 요약(접기/펼치기 비활성).
  if (depth >= MAX_DEPTH) {
    return (
      <div style={{ paddingLeft: depth * PAD }}>
        <Caret state="none" />
        {keyEl}
        <Punc t={ob} />
        <span style={{ color: 'var(--color-text-quaternary)' }}>
          {' '}… {n} {isArr ? 'items' : 'keys'} {cb}
          {comma}
        </span>
      </div>
    )
  }

  const shown = entries.slice(0, CHILD_CAP)
  const hidden = n - shown.length

  return (
    <>
      <div
        style={{ paddingLeft: depth * PAD, cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen((o) => !o)}
      >
        <Caret state={open ? 'open' : 'closed'} />
        {keyEl}
        <Punc t={ob} />
        {!open && (
          <span style={{ color: 'var(--color-text-quaternary)' }}>
            {' '}… {n} {isArr ? 'items' : 'keys'} {cb}
            {comma}
          </span>
        )}
      </div>
      {open && (
        <>
          {shown.map(([ck, cv], i) => (
            <Node key={i} keyName={ck} value={cv} isLast={hidden === 0 && i === n - 1} depth={depth + 1} />
          ))}
          {hidden > 0 && (
            <div style={{ paddingLeft: (depth + 1) * PAD, color: 'var(--color-text-quaternary)' }}>
              <Caret state="none" />… {hidden} {isArr ? 'items' : 'keys'} 더(생략)
            </div>
          )}
          <div style={{ paddingLeft: depth * PAD }}>
            <Caret state="none" />
            <Punc t={cb + comma} />
          </div>
        </>
      )}
    </>
  )
}

export function JsonTree({ value }: { value: unknown }) {
  return (
    <div
      style={{
        fontFamily: MONO,
        fontSize: 12.5,
        lineHeight: 1.6,
        overflowX: 'auto',
        background: 'var(--gray-2)',
        border: '1px solid var(--gray-4)',
        borderRadius: 8,
        padding: '8px 8px',
      }}
    >
      <Node value={value} isLast depth={0} />
    </div>
  )
}
