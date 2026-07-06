/* my-agents debug console — right rail: per-turn Inspector.
   Shows the resolved system prompt, retrieved memories, MCP tool calls and the
   LangGraph execution path for the currently-selected assistant turn. */
import { useState, useEffect, type CSSProperties, type ReactNode } from 'react'
import { Tag, Button, Collapse } from 'antd'
import { Icon } from '../admin/icons'
import type { ChatMsg, Memory, McpCallT, GraphNode, Trace, RagHit } from './agentData'
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

/* 유사도 점수대별 색(스펙 191) — score=1−cosine_distance(1=완전 일치). 표시 heuristic 밴드:
   ≥0.7 강함(green)·0.5~0.7 보통(default)·<0.5 약함(orange). 임베딩 모델 무관 고정. */
function scoreColor(score: number): string {
  if (score >= 0.7) return 'green'
  if (score >= 0.5) return 'default'
  return 'orange'
}

/* 유사도 척도 범례(스펙 191) — "0.42가 낮은 건가?" 질문에 답한다. thresholds 있으면 컬렉션별 기준선도. */
function ScaleLegend({ thresholds }: { thresholds?: Record<string, number> }) {
  const entries = Object.entries(thresholds || {}).filter(([, v]) => typeof v === 'number' && v > 0)
  return (
    <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
      유사도 0~1 (1=완전 일치, 0.5 미만=관련 낮음)
      {entries.length ? (
        <> · <span style={{ color: 'var(--color-warning)' }}>필터: {entries.map(([c, v]) => `${c} ≥ ${v.toFixed(2)}`).join(', ')} 미만 제외</span></>
      ) : null}
    </div>
  )
}

/* RAG 히트 1건 카드(스펙 191) — 컬렉션 + 파일명 + 유사도 배지(점수대 색) + 본문 프리뷰(길면 접기).
   벽 텍스트를 문서별로 갈라 스캔 가능하게. */
function HitCard({ hit, idx }: { hit: RagHit; idx: number }) {
  const long = hit.textPreview.length > 160
  const body = (
    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
      {hit.textPreview || '(본문 없음)'}
    </div>
  )
  return (
    <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 6, padding: '6px 10px', marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: long ? 0 : 4 }}>
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', flex: 'none' }}>{idx + 1}.</span>
        {hit.collection ? (
          <Tag color="geekblue" style={{ fontSize: 11, marginInlineEnd: 0 }}>{hit.collection}</Tag>
        ) : null}
        <span style={{ fontSize: 12, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-heading)', overflowWrap: 'anywhere' }}>
          {hit.filename || '(파일명 없음)'}
        </span>
        <Tag color={scoreColor(hit.score)} style={{ marginInlineStart: 2 }}>유사도 {hit.score.toFixed(3)}</Tag>
      </div>
      {long ? (
        <Collapse
          size="small"
          ghost
          items={[{ key: 'b', label: <span style={{ fontSize: 12 }}>본문 보기</span>, children: body }]}
        />
      ) : (
        body
      )}
    </div>
  )
}

/* RAG 문서검색 호출 카드(스펙 079) — McpCall과 형제지만 hits(반환 건수)를 강조하고
   "문서 검색" 맥락으로 라벨링한다. 0건이어도 조회 이력으로 남긴다.
   스펙 191: 결과를 벽 텍스트 대신 히트별 카드로(hitsDetail 있으면), 유사도 척도 범례 노출. */
function RagCall({ c }: { c: McpCallT }) {
  const q = typeof c.args?.query === 'string' ? (c.args.query as string) : ''
  const n = c.hits ?? 0
  const detail = c.hitsDetail ?? []
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
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>검색어</div>
      <pre style={{ ...codeBox, marginBottom: 8 }}>{q || '(빈 검색어)'}</pre>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>결과</div>
      {detail.length ? (
        <>
          <ScaleLegend thresholds={c.minScores} />
          {detail.map((h, i) => <HitCard key={i} hit={h} idx={i} />)}
        </>
      ) : (
        // 옛 trace(hitsDetail 없음) 하위호환 — 기존 텍스트 폴백.
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{c.result}</div>
      )}
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
                {/* 병렬 superstep이면 ms는 청크 공유값 — '순차 +Xms'로 과장하지 않고 '병렬 ⏱Xms'로 정직 표기(F4). */}
                {n.parallel ? `병렬 ⏱${n.ms}ms` : `+${n.ms}ms`}
              </span>
              {/* 그 노드가 바꾼 상태 델타 요약(스펙 086) — 있을 때만. 이름이 아니라 *내용*으로 읽힌다. */}
              {n.summary ? (
                <div
                  style={{
                    flexBasis: '100%',
                    fontSize: 12,
                    color: 'var(--color-text-secondary)',
                    fontFamily: 'var(--font-family-code)',
                    overflowWrap: 'anywhere',
                    marginTop: 2,
                  }}
                >
                  {n.summary}
                </div>
              ) : null}
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
  // Escape 닫기(스펙 135) — 모바일은 불투명 전체화면 오버레이라 X 하나에 의존하던 것을 보완.
  // 훅은 early-return 이전에 무조건 호출(규칙).
  useEffect(() => {
    if (!onClose) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
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

          {/* 전송 프롬프트(스펙 131) — 실제 LLM에 넣은 메시지 배열(조립 system=persona+회상 포함).
              trace.sentMessages 있으면 그것을(충실본), 없으면(구 트레이스·재개 턴) 정적 persona 폴백.
              user 입력은 채팅 버블에서 이미 보이므로 **표시에서 제외**(사용자 요청 — 데이터는 보존). */}
          {t.sentMessages?.length ? (
            (() => {
              const shown = t.sentMessages.filter((m) => m.role !== 'user')
              return (
                <Section icon="file" iconColor="var(--color-primary)" title="전송 프롬프트" count={t.sentMessages.length}>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
                    이 턴에 모델로 전송된 메시지 {t.sentMessages.length}개(회상 주입 포함 · 메시지당 2000자
                    표시 상한). user 입력 {t.sentMessages.length - shown.length}개는 채팅에서 확인 — 표시 생략.
                  </div>
                  <Collapse
                    size="small"
                    defaultActiveKey={['m0']}
                    items={shown.map((m, i) => ({
                      key: `m${i}`,
                      label: (
                        <span>
                          <Tag color={m.role === 'system' ? 'blue' : 'green'}>{m.role}</Tag>
                          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{m.content.length}자</span>
                        </span>
                      ),
                      children: <pre style={codeBox}>{m.content}</pre>,
                    }))}
                  />
                </Section>
              )
            })()
          ) : (
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
          )}

          {/* 이 턴에 적용된 오버라이드(스펙 134) — 세션에 설정 다른 턴이 섞여도 턴별로 영구 구분. */}
          {t.overrides && Object.keys(t.overrides).length ? (
            <Section icon="experiment" iconColor="var(--gold-6)" title="오버라이드 (이 턴 적용)" count={Object.keys(t.overrides).length}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                {Object.entries(t.overrides).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                    <span style={{ width: 100, flex: 'none', color: 'var(--color-text-tertiary)' }}>{k}</span>
                    {Array.isArray(v) ? (
                      <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {v.map((it, i) => (
                          <Tag key={i} style={{ margin: 0, whiteSpace: 'normal', height: 'auto', overflowWrap: 'anywhere' }}>{String(it)}</Tag>
                        ))}
                      </span>
                    ) : (
                      <span style={{ fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere' }}>{String(v)}</span>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          ) : null}

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
              해 도구를 안 불렀어도 RAG가 가용했는지 보인다(스펙 079). 조율형의 **브로커 경유 RAG**도
              여기에 표면화(스펙 130) — 이전엔 그래프 노드명뿐이라 "검색 안 함"으로 오인됐다. */}
          {(() => {
            const ragCalls = t.mcp.filter((c) => c.server === 'rag')
            const brokerRag = (t.brokerCalls ?? []).filter((b) => b.cap_id.startsWith('rag:'))
            const cols = t.ragCollections ?? []
            const unresolved = t.ragUnresolved ?? []
            if (!ragCalls.length && !brokerRag.length && !cols.length && !unresolved.length) return null
            return (
              <Section icon="search" iconColor="var(--geekblue-6)" title="문서 검색 (RAG)" count={ragCalls.length + brokerRag.length}>
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
                {/* 브로커 위임 검색(조율형, 스펙 130) — 건수·최고 유사도·판정 태그.
                    131: 결과 본문 프리뷰를 접이식으로(2000자 캡·마스킹된 안전본).
                    191: 검색어 노출 + 히트별 카드(hitsDetail) + 유사도 척도/기준선. */}
                {brokerRag.map((b, i) => {
                  const bd = (b.hitsDetail ?? []) as RagHit[]
                  return (
                  <div key={`bk-${i}`} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13 }}>
                      <Tag color="geekblue" style={{ fontFamily: 'var(--font-family-code)' }}>{b.cap_id}</Tag>
                      {b.error ? (
                        <Tag color="red">검색 실패</Tag>
                      ) : (
                        <>
                          <span>검색 {b.hits ?? 0}건</span>
                          {/* 유사도·판정은 topScore가 **실측 숫자일 때만** — 없는데 0.000/관련도낮음으로
                              오표시하지 않는다(codex 130 P3). */}
                          {b.hits && typeof b.topScore === 'number' ? (
                            <span style={{ color: 'var(--color-text-secondary)' }}>· 최고 유사도 {b.topScore.toFixed(3)}</span>
                          ) : null}
                          {b.hits && typeof b.topScore === 'number' && b.topScore < 0.5 ? (
                            <Tag color="orange">관련도 낮음</Tag>
                          ) : null}
                          {!b.hits ? <Tag color="default">0건</Tag> : null}
                        </>
                      )}
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{b.ms}ms</span>
                    </div>
                    {/* 검색어(스펙 191) — 직접 도구와 동일하게 무엇으로 검색했는지 노출. */}
                    {b.query ? (
                      <div style={{ marginTop: 4 }}>
                        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>검색어: </span>
                        <span style={{ fontSize: 12, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{b.query}</span>
                      </div>
                    ) : null}
                    {bd.length ? (
                      <div style={{ marginTop: 6 }}>
                        {/* 브로커 rag 호출은 컬렉션 1개(cap_id="rag:컬렉션명") → minScore(scalar)를 그 컬렉션 기준선으로. */}
                        <ScaleLegend thresholds={b.minScore ? { [b.cap_id.replace(/^rag:/, '')]: b.minScore } : undefined} />
                        {bd.map((h, j) => <HitCard key={j} hit={h} idx={j} />)}
                      </div>
                    ) : b.resultPreview ? (
                      <Collapse
                        size="small"
                        style={{ marginTop: 4 }}
                        items={[{ key: 'r', label: <span style={{ fontSize: 12 }}>검색 결과 본문</span>, children: <pre style={codeBox}>{b.resultPreview}</pre> }]}
                      />
                    ) : null}
                  </div>
                  )
                })}
                {ragCalls.length ? (
                  ragCalls.map((c, i) => <RagCall key={i} c={c} />)
                ) : !brokerRag.length ? (
                  <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>이 턴에서는 문서 검색을 호출하지 않았습니다.</div>
                ) : null}
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

          {/* 비-RAG 브로커 위임 호출(스펙 131, codex #4) — mcp:/memory:/agent: 능력도 결과 본문을
              표면화(부분 표면화=새 사각지대, 130 교훈). rag:* 는 위 RAG 섹션이 담당. */}
          {(() => {
            const others = (t.brokerCalls ?? []).filter((b) => !b.cap_id.startsWith('rag:'))
            if (!others.length) return null
            return (
              <Section icon="share-alt" iconColor="var(--gold-6)" title="위임 호출 (브로커)" count={others.length}>
                {others.map((b, i) => (
                  <div key={`ob-${i}`} style={{ marginBottom: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13 }}>
                      <Tag color="gold" style={{ fontFamily: 'var(--font-family-code)' }}>{b.cap_id}</Tag>
                      {b.error ? <Tag color="red">실패</Tag> : null}
                      {typeof b.hits === 'number' ? <span>{b.hits}건</span> : null}
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{b.ms}ms</span>
                    </div>
                    {b.resultPreview ? (
                      <Collapse
                        size="small"
                        style={{ marginTop: 4 }}
                        items={[{ key: 'r', label: <span style={{ fontSize: 12 }}>결과 본문</span>, children: <pre style={codeBox}>{b.resultPreview}</pre> }]}
                      />
                    ) : null}
                  </div>
                ))}
              </Section>
            )
          })()}

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
