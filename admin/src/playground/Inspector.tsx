/* my-agents debug console — right rail: per-turn Inspector.
   Shows the resolved system prompt, retrieved memories, MCP tool calls and the
   LangGraph execution path for the currently-selected assistant turn. */
import { useState, type CSSProperties, type ReactNode } from 'react'
import { Tag, Button } from 'antd'
import { Icon } from '../admin/icons'
import type { ChatMsg, Memory, McpCallT, GraphNode, Trace } from './agentData'
import type { Agent } from '../admin/mockData'

function Section({
  icon,
  iconColor,
  title,
  count,
  children,
  defaultOpen = true,
}: {
  icon: string
  iconColor: string
  title: string
  count?: number
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid var(--color-border-secondary)' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '12px 16px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <span style={{ color: iconColor, display: 'inline-flex' }}>
          <Icon name={icon} size={15} />
        </span>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', flex: 1, textAlign: 'left' }}>
          {title}
        </span>
        {count != null ? <Tag>{count}</Tag> : null}
        <span
          style={{
            color: 'var(--color-text-tertiary)',
            transform: open ? 'rotate(90deg)' : 'none',
            transition: 'transform .2s',
            display: 'inline-flex',
          }}
        >
          <Icon name="right" size={11} />
        </span>
      </button>
      {open ? <div style={{ padding: '0 16px 16px' }}>{children}</div> : null}
    </div>
  )
}

const codeBox: CSSProperties = {
  fontFamily: 'var(--font-family-code)',
  fontSize: 12,
  lineHeight: 1.6,
  color: 'var(--color-text)',
  background: 'var(--gray-2)',
  border: '1px solid var(--color-border-secondary)',
  borderRadius: 6,
  padding: '10px 12px',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  margin: 0,
  overflow: 'auto',
}

function MemoryRow({ m }: { m: Memory }) {
  const pct = Math.round(m.score * 100)
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: '10px 0',
        borderTop: '1px solid var(--color-border-secondary)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag color={m.type === 'semantic' ? 'geekblue' : 'purple'}>{m.type}</Tag>
        {m.scope ? (
          <Tag color={m.scope === 'user_id' ? 'green' : 'default'}>
            {m.scope === 'user_id' ? '유저 장기' : m.scope === 'run_id' ? '세션' : m.scope}
          </Tag>
        ) : null}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>{pct}%</span>
      </div>
      <div style={{ fontSize: 13, color: 'var(--color-text)', lineHeight: 1.5, overflowWrap: 'anywhere' }}>{m.text}</div>
      <div style={{ height: 4, background: 'var(--color-fill-secondary)', borderRadius: 100, overflow: 'hidden' }}>
        <div style={{ width: pct + '%', height: '100%', background: 'var(--geekblue-5)', borderRadius: 100 }} />
      </div>
    </div>
  )
}

function McpCall({ c }: { c: McpCallT }) {
  return (
    <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 8, padding: 12, marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap', rowGap: 2 }}>
        <Icon
          name={c.status === 'ok' ? 'check-circle' : 'close-circle'}
          size={14}
          style={{ color: c.status === 'ok' ? 'var(--color-success)' : 'var(--color-error)', flex: 'none' }}
        />
        <span
          style={{
            fontSize: 13,
            fontFamily: 'var(--font-family-code)',
            color: 'var(--color-text-heading)',
            minWidth: 0,
            overflowWrap: 'anywhere',
          }}
        >
          <span style={{ color: 'var(--cyan-7)' }}>{c.server}</span>.{c.tool}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)', flex: 'none' }}>{c.ms} ms</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>args</div>
      <pre style={{ ...codeBox, marginBottom: 8 }}>{JSON.stringify(c.args)}</pre>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>result</div>
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{c.result}</div>
    </div>
  )
}

/* RAG 문서검색 호출 카드(스펙 079) — McpCall과 형제지만 hits(반환 건수)를 강조하고
   "문서 검색" 맥락으로 라벨링한다. 0건이어도 조회 이력으로 남긴다. */
function RagCall({ c }: { c: McpCallT }) {
  const q = typeof c.args?.query === 'string' ? (c.args.query as string) : ''
  const n = c.hits ?? 0
  return (
    <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 8, padding: 12, marginTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap', rowGap: 2 }}>
        <Icon
          name={c.status === 'ok' ? 'check-circle' : 'close-circle'}
          size={14}
          style={{ color: c.status === 'ok' ? 'var(--color-success)' : 'var(--color-error)', flex: 'none' }}
        />
        <span style={{ fontSize: 13, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-heading)' }}>
          search_documents
        </span>
        <Tag color={n > 0 ? 'green' : 'default'} style={{ marginInlineStart: 2 }}>{n}건</Tag>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)', flex: 'none' }}>{c.ms} ms</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>쿼리</div>
      <pre style={{ ...codeBox, marginBottom: 8 }}>{q || '(빈 쿼리)'}</pre>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>결과</div>
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{c.result}</div>
    </div>
  )
}

function GraphPath({ graph }: { graph: GraphNode[] }) {
  const special: Record<string, string> = {
    interrupt: 'var(--gold-6)',
    checkpoint_load: 'var(--purple-6)',
    checkpoint_save: 'var(--purple-6)',
    resume: 'var(--purple-6)',
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {graph.map((n, i) => {
        const term = n.node.startsWith('__')
        const sp = special[n.node]
        const dot = sp || (term ? 'var(--gray-6)' : 'var(--color-primary)')
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 'none' }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', flex: 'none', background: dot }} />
              {i < graph.length - 1 ? <span style={{ width: 2, height: 22, background: 'var(--color-border)' }} /> : null}
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
                flexWrap: 'wrap',
                minWidth: 0,
                paddingBottom: i < graph.length - 1 ? 14 : 0,
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  fontFamily: 'var(--font-family-code)',
                  color: sp ? sp : term ? 'var(--color-text-tertiary)' : 'var(--color-text-heading)',
                  overflowWrap: 'anywhere',
                  minWidth: 0,
                }}
              >
                {n.node}
              </span>
              <span style={{ fontSize: 11, color: 'var(--color-text-quaternary)', fontFamily: 'var(--font-family-code)', flex: 'none' }}>
                +{n.ms}ms
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-text-heading)', fontFamily: 'var(--font-family-code)' }}>
        {value}
      </div>
    </div>
  )
}

export function Inspector({
  agent,
  turn,
  turnIndex,
  onClose,
  fullWidth = false,
}: {
  agent: Agent | null
  turn: ChatMsg | null
  turnIndex: number
  onClose?: () => void
  fullWidth?: boolean
}) {
  if (!agent) return null
  const t: Trace | undefined = turn && turn.role === 'ai' ? turn.trace : undefined
  const empty = !t
  return (
    <aside
      style={{
        width: fullWidth ? '100%' : 384,
        flex: 'none',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-bg-container)',
        borderLeft: '1px solid var(--color-border-secondary)',
      }}
    >
      <div
        style={{
          flex: 'none',
          padding: '14px 16px',
          borderBottom: '1px solid var(--color-border-secondary)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Icon name="dashboard" size={16} style={{ color: 'var(--color-text-secondary)' }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-heading)', flex: 1 }}>턴 인스펙터</span>
        {!empty ? <Tag color="blue">턴 {turnIndex + 1}</Tag> : null}
        {onClose ? <Button type="text" size="small" icon={<Icon name="close" />} onClick={onClose} /> : null}
      </div>

      {empty || !t ? (
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            color: 'var(--color-text-tertiary)',
            padding: 24,
            textAlign: 'center',
          }}
        >
          <Icon name="thunderbolt" size={28} style={{ color: 'var(--color-text-quaternary)' }} />
          <div style={{ fontSize: 13 }}>
            메시지를 보낸 뒤, 어시스턴트 턴을 선택하면
            <br />
            트레이스를 확인할 수 있습니다.
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {/* metrics strip */}
          <div style={{ display: 'flex', gap: 0, padding: '12px 16px', borderBottom: '1px solid var(--color-border-secondary)' }}>
            <Metric label="지연시간" value={(t.latencyMs / 1000).toFixed(2) + 's'} />
            <Metric label="입력 토큰" value={t.tokens.in.toLocaleString()} />
            <Metric label="출력 토큰" value={t.tokens.out.toLocaleString()} />
          </div>

          <Section icon="file" iconColor="var(--color-primary)" title="시스템 프롬프트">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap', rowGap: 6 }}>
              <Tag color="blue" style={{ whiteSpace: 'normal', height: 'auto', maxWidth: '100%', overflowWrap: 'anywhere' }}>
                {agent.name}
              </Tag>
              {(agent.memories || []).map((m) => (
                <Tag key={m} color="purple" style={{ whiteSpace: 'normal', height: 'auto', maxWidth: '100%', overflowWrap: 'anywhere' }}>
                  {m}
                </Tag>
              ))}
            </div>
            <pre style={codeBox}>{agent.systemPrompt}</pre>
          </Section>

          <Section icon="bulb" iconColor="var(--purple-6)" title="메모리" count={t.memories.length}>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>메모리 타입: {(agent.memories || []).join(', ')}</div>
            {/* 회상 조회 이력(스펙 079) — 0건이어도 "조회 행위"를 남긴다. memoryQuery 있을 때만. */}
            {t.memoryQuery != null ? (
              <div
                style={{
                  marginTop: 8,
                  padding: '8px 10px',
                  background: 'var(--gray-2)',
                  border: '1px solid var(--color-border-secondary)',
                  borderRadius: 6,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <Icon name="search" size={12} style={{ color: 'var(--purple-6)' }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-heading)' }}>회상 조회</span>
                  <Tag color={t.memories.length > 0 ? 'purple' : 'default'} style={{ marginInlineStart: 2 }}>
                    {t.memories.length}건 회상
                  </Tag>
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere' }}>
                  «{t.memoryQuery}»
                </div>
              </div>
            ) : null}
            {t.memoryScope ? (
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
                스코프:{' '}
                {t.memoryScope.user_id ? (
                  <Tag
                    color="green"
                    style={{ marginInlineEnd: 4, whiteSpace: 'normal', height: 'auto', maxWidth: '100%', overflowWrap: 'anywhere' }}
                  >
                    유저 장기 · {t.memoryScope.user_id}
                  </Tag>
                ) : null}
                {t.memoryScope.run_id ? (
                  <Tag
                    color="default"
                    style={{ marginInlineEnd: 0, whiteSpace: 'normal', height: 'auto', maxWidth: '100%', overflowWrap: 'anywhere' }}
                  >
                    세션 · {t.memoryScope.run_id}
                  </Tag>
                ) : null}
              </div>
            ) : null}
            {t.memories.map((m, i) => (
              <MemoryRow key={i} m={m} />
            ))}
          </Section>

          {/* 문서 검색(RAG) 이력 — RAG 호출은 MCP에서 분리해 전용 섹션에. 연결 컬렉션/미해석도 노출
              해 도구를 안 불렀어도 RAG가 가용했는지 보인다(스펙 079). 셋 다 없으면 섹션 숨김(무회귀). */}
          {(() => {
            const ragCalls = t.mcp.filter((c) => c.server === 'rag')
            const cols = t.ragCollections ?? []
            const unresolved = t.ragUnresolved ?? []
            if (!ragCalls.length && !cols.length && !unresolved.length) return null
            return (
              <Section icon="search" iconColor="var(--geekblue-6)" title="문서 검색 (RAG)" count={ragCalls.length}>
                {cols.length ? (
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>연결 컬렉션:</span>
                    {cols.map((name) => (
                      <Tag key={name} color="geekblue" style={{ whiteSpace: 'normal', height: 'auto', maxWidth: '100%', overflowWrap: 'anywhere' }}>
                        {name}
                      </Tag>
                    ))}
                  </div>
                ) : null}
                {unresolved.length ? (
                  <div style={{ fontSize: 12, color: 'var(--color-warning)', marginBottom: 8, overflowWrap: 'anywhere' }}>
                    ⚠ 미해석 컬렉션(임베딩 모델/프로바이더 불완전): {unresolved.join(', ')}
                  </div>
                ) : null}
                {ragCalls.length ? (
                  ragCalls.map((c, i) => <RagCall key={i} c={c} />)
                ) : (
                  <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>이 턴에서는 문서 검색을 호출하지 않았습니다.</div>
                )}
              </Section>
            )
          })()}

          <Section icon="thunderbolt" iconColor="var(--cyan-7)" title="MCP 도구 호출" count={t.mcp.filter((c) => c.server !== 'rag').length}>
            {t.mcp.filter((c) => c.server !== 'rag').length ? (
              t.mcp.filter((c) => c.server !== 'rag').map((c, i) => <McpCall key={i} c={c} />)
            ) : (
              <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>호출된 도구 없음.</div>
            )}
          </Section>

          <Section icon="share-alt" iconColor="var(--green-6)" title="LangGraph 경로" count={t.graph.length}>
            {t.resumedFrom ? (
              <div style={{ fontSize: 12, color: 'var(--purple-7)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name="clock-circle" size={12} />
                체크포인트에서 재개됨 <code style={{ fontFamily: 'var(--font-family-code)' }}>{t.resumedFrom}</code>
              </div>
            ) : null}
            <GraphPath graph={t.graph} />
          </Section>
        </div>
      )}
    </aside>
  )
}
