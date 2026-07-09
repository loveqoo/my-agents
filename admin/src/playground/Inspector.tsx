/* my-agents debug console — right rail: per-turn Inspector.
   Shows the resolved system prompt, retrieved memories, MCP tool calls and the
   LangGraph execution path for the currently-selected assistant turn. */
import { useState, useEffect, type CSSProperties, type ReactNode } from 'react'
import { Tag, Button, Collapse, Timeline, Tabs, Modal, Progress, Alert } from 'antd'
import { Icon } from '../admin/icons'
import { parseEntityText, EntityFields } from '../admin/EntityFields'
import type { ChatMsg, Memory, McpCallT, Trace, RagHit } from './agentData'
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
  // antd Collapse로 통일(스펙 204) — 수제 버튼+회전 셰브론+useState 제거, 접이 상태·접근성을 antd에 이양.
  return (
    <Collapse
      ghost
      defaultActiveKey={defaultOpen ? ['s'] : []}
      style={{ borderBottom: '1px solid var(--color-border-secondary)', borderRadius: 0 }}
      items={[{
        key: 's',
        label: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: iconColor, display: 'inline-flex' }}><Icon name={icon} size={15} /></span>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', flex: 1, textAlign: 'left' }}>{title}</span>
            {count != null ? <Tag>{count}</Tag> : null}
          </span>
        ),
        children,
      }]}
    />
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
  overflowWrap: 'anywhere',
  margin: 0,
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
      {/* antd Progress로 통일(스펙 204) — 수치 표기는 위 pct% 텍스트가 담당. */}
      <Progress percent={pct} size={{ height: 4 }} showInfo={false} strokeColor="var(--geekblue-5)" />
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
  const dropped = hit.belowCutoff === true // 스펙 192: 커트라인 미달로 에이전트가 못 쓴 문서
  // 엔티티 직렬화 텍스트(스펙 255) — 검색 시험 카드와 같은 구조화 렌더(빈 필드 접기). 공용 EntityFields.
  const parsed = hit.textPreview ? parseEntityText(hit.textPreview) : null
  const body = parsed ? (
    <EntityFields rows={parsed.rows} empty={parsed.empty} size={12} />
  ) : (
    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
      {hit.textPreview || '(본문 없음)'}
    </div>
  )
  return (
    <div
      style={{
        border: '1px solid var(--color-border-secondary)',
        borderRadius: 6,
        padding: '6px 10px',
        marginTop: 6,
        opacity: dropped ? 0.6 : 1, // 못 쓴 문서는 흐리게
        background: dropped ? 'var(--gray-2)' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: long ? 0 : 4 }}>
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', flex: 'none' }}>{idx + 1}.</span>
        {hit.collection ? (
          <Tag color="geekblue" style={{ fontSize: 11, marginInlineEnd: 0 }}>{hit.collection}</Tag>
        ) : null}
        <span style={{ fontSize: 12, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-heading)', overflowWrap: 'anywhere' }}>
          {hit.filename || '(파일명 없음)'}
        </span>
        <Tag color={dropped ? 'default' : scoreColor(hit.score)} style={{ marginInlineStart: 2 }}>유사도 {hit.score.toFixed(3)}</Tag>
        {dropped ? (
          <Tag color="default" style={{ marginInlineStart: 0 }}>
            ✗ 커트라인 {typeof hit.cutoff === 'number' ? hit.cutoff.toFixed(2) : ''} 미달 · 미사용
          </Tag>
        ) : null}
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

/* ── 스펙 192: 단계(노드)별 실행 타임라인 ─────────────────────────────
   trace를 "자원 종류별"이 아니라 "실행 노드별"로 재조립한다. 이벤트→노드 귀속(추측 아님, 기존 데이터):
   - 브로커 호출: brokerCalls[].node = broker_invoke:<cap_id> → 같은 이름의 그래프 노드에 귀속.
   - 직접 경로: calls_sink(t.mcp)엔 node 없음 → 직접 그래프가 선형(retrieve_memory→tools→call_model)이라
     타입으로 귀속(회상→retrieve_memory, rag/mcp→tools, 토큰→call_model). ReAct 다중 tools는 한 노드로 접힘. */

type BrokerCall = NonNullable<Trace['brokerCalls']>[number]

// 노드명 → 사람이 읽는 라벨·아이콘·색.
function nodeMeta(node: string): { text: string; icon: string; color: string } {
  const known: Record<string, { text: string; icon: string; color: string }> = {
    __start__: { text: '시작', icon: 'play-circle', color: 'var(--gray-6)' },
    __end__: { text: '종료', icon: 'check-circle', color: 'var(--gray-6)' },
    retrieve_memory: { text: '메모리 회상', icon: 'bulb', color: 'var(--purple-6)' },
    tools: { text: '도구·문서 검색 실행', icon: 'thunderbolt', color: 'var(--cyan-7)' },
    model: { text: '모델 호출', icon: 'message', color: 'var(--color-primary)' },
    call_model: { text: '모델 호출', icon: 'message', color: 'var(--color-primary)' },
    agent: { text: '모델 호출', icon: 'message', color: 'var(--color-primary)' },
    interrupt: { text: '중단(승인 대기)', icon: 'pause-circle', color: 'var(--gold-6)' },
    checkpoint_load: { text: '체크포인트 로드', icon: 'clock-circle', color: 'var(--purple-6)' },
    checkpoint_save: { text: '체크포인트 저장', icon: 'clock-circle', color: 'var(--purple-6)' },
    resume: { text: '재개', icon: 'clock-circle', color: 'var(--purple-6)' },
  }
  if (known[node]) return known[node]
  if (node.startsWith('broker_invoke:rag:'))
    return { text: `문서 검색 위임 · ${node.slice('broker_invoke:rag:'.length)}`, icon: 'search', color: 'var(--geekblue-6)' }
  if (node.startsWith('broker_invoke:mcp:'))
    return { text: `도구 위임 · ${node.slice('broker_invoke:mcp:'.length)}`, icon: 'thunderbolt', color: 'var(--cyan-7)' }
  if (node.startsWith('broker_invoke:'))
    return { text: `위임 · ${node.slice('broker_invoke:'.length)}`, icon: 'share-alt', color: 'var(--gold-6)' }
  return { text: node, icon: 'dot-chart', color: 'var(--color-primary)' }
}

// 브로커 RAG 호출 1건 상세(검색어·건수·최고유사도·히트 카드) — 노드 타임라인·폴백 양쪽서 재사용.
function BrokerRagCard({ b }: { b: BrokerCall }) {
  const bd = (b.hitsDetail ?? []) as RagHit[]
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13 }}>
        {b.error ? <Tag color="red">검색 실패</Tag> : <span>검색 {b.hits ?? 0}건 사용</span>}
        {b.hits && typeof b.topScore === 'number' ? (
          <span style={{ color: 'var(--color-text-secondary)' }}>· 최고 유사도 {b.topScore.toFixed(3)}</span>
        ) : null}
        {!b.hits && !b.error ? <Tag color="default">0건</Tag> : null}
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{b.ms}ms</span>
      </div>
      {b.query ? (
        <div style={{ marginTop: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>검색어: </span>
          <span style={{ fontSize: 12, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{b.query}</span>
        </div>
      ) : null}
      {bd.length ? (
        <div style={{ marginTop: 6 }}>
          <ScaleLegend thresholds={b.minScore ? { [b.cap_id.replace(/^rag:/, '')]: b.minScore } : undefined} />
          {bd.map((h, j) => <HitCard key={j} hit={h} idx={j} />)}
        </div>
      ) : b.resultPreview ? (
        <Collapse size="small" style={{ marginTop: 4 }}
          items={[{ key: 'r', label: <span style={{ fontSize: 12 }}>검색 결과 본문</span>, children: <pre style={codeBox}>{b.resultPreview}</pre> }]} />
      ) : null}
    </div>
  )
}

// 한 노드에서 일어난 일의 상세 JSX(없으면 null). t.graph의 각 노드에 붙는다.
// tctx: tools 노드 라운드 귀속용(스펙 202/203 후속) — 이 tools 노드의 순번·전체 수·요약(내용 매칭 키).
function nodeEventContent(
  t: Trace,
  node: string,
  tctx?: { summary?: string; toolsIdx: number; toolsTotal: number },
): ReactNode | null {
  // 메모리 회상 — retrieve_memory 노드.
  if (node === 'retrieve_memory' && (t.memoryQuery != null || t.memories.length)) {
    return (
      <div>
        {t.memoryQuery != null ? (
          <div style={{ fontSize: 12, marginBottom: 6 }}>
            <span style={{ color: 'var(--color-text-tertiary)' }}>회상 쿼리: </span>
            <span style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>«{t.memoryQuery}»</span>
            <Tag color={t.memories.length ? 'purple' : 'default'} style={{ marginInlineStart: 6 }}>{t.memories.length}건 회상</Tag>
          </div>
        ) : null}
        {t.memoryScope?.user_id || t.memoryScope?.run_id ? (
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>
            스코프: {t.memoryScope.user_id ? `유저 장기(${t.memoryScope.user_id})` : ''}{t.memoryScope.user_id && t.memoryScope.run_id ? ' · ' : ''}{t.memoryScope.run_id ? `세션(${t.memoryScope.run_id})` : ''}
          </div>
        ) : null}
        {t.memories.map((m, i) => <MemoryRow key={i} m={m} />)}
      </div>
    )
  }
  // 도구·문서검색(직접 경로) — tools 노드에 t.mcp 귀속.
  // 스펙 202/203 후속(도시락 버그): 도구 루프가 생기며 tools 노드가 **여러 번** 등장할 수 있는데,
  // 전부-귀속(옛 가정 "ReAct 다중 tools는 한 노드로 접힘")이면 라운드마다 같은 카드가 중복 렌더된다
  // (3회 호출 턴 = 카드 9장). 다회면 ① 결과 본문 머리가 이 라운드 summary에 포함되는 호출만(내용
  // 매칭), ② 매칭 0건이면 순번 폴백(라운드 수=호출 수인 통상 케이스)으로 라운드별 귀속한다.
  if (node === 'tools') {
    let calls = t.mcp
    if (tctx && tctx.toolsTotal > 1) {
      const sum = tctx.summary || ''
      const matched = t.mcp.filter((c) => {
        const head = String(c.result ?? '').slice(0, 40)
        return head.length > 0 && sum.includes(head)
      })
      calls = matched.length ? matched : t.mcp[tctx.toolsIdx] ? [t.mcp[tctx.toolsIdx]] : []
    }
    const rag = calls.filter((c) => c.server === 'rag')
    const mcp = calls.filter((c) => c.server !== 'rag')
    if (!rag.length && !mcp.length) return null
    return (
      <div>
        {rag.map((c, i) => <RagCall key={`r${i}`} c={c} />)}
        {mcp.map((c, i) => <McpCall key={`m${i}`} c={c} />)}
      </div>
    )
  }
  // 브로커 위임(조율형) — broker_invoke:<cap_id> 노드에 그 cap 호출 귀속.
  if (node.startsWith('broker_invoke:')) {
    const calls = (t.brokerCalls ?? []).filter((b) => `broker_invoke:${b.cap_id}` === node)
    if (!calls.length) return null
    return (
      <div>
        {calls.map((b, i) =>
          b.cap_id.startsWith('rag:') ? (
            <BrokerRagCard key={i} b={b} />
          ) : (
            <div key={i} style={{ marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13 }}>
                <Tag color="gold" style={{ fontFamily: 'var(--font-family-code)' }}>{b.cap_id}</Tag>
                {b.error ? <Tag color="red">실패</Tag> : null}
                {typeof b.hits === 'number' ? <span>{b.hits}건</span> : null}
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{b.ms}ms</span>
              </div>
              {b.resultPreview ? (
                <Collapse size="small" style={{ marginTop: 4 }}
                  items={[{ key: 'r', label: <span style={{ fontSize: 12 }}>결과 본문</span>, children: <pre style={codeBox}>{b.resultPreview}</pre> }]} />
              ) : null}
            </div>
          )
        )}
      </div>
    )
  }
  // 모델 호출 — 토큰 요약.
  if (node === 'call_model') {
    return (
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
        입력 {t.tokens.in.toLocaleString()} · 출력 {t.tokens.out.toLocaleString()} 토큰
      </div>
    )
  }
  return null
}

// 단계별 실행 타임라인 — antd Timeline을 스파인으로, 각 노드에 상세를 접이식으로.
function NodeTimeline({ t }: { t: Trace }) {
  if (!t.graph.length) {
    return <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>실행 경로 정보가 없습니다(재개 턴 등).</div>
  }
  return (
    <div>
      {t.resumedFrom ? (
        <div style={{ fontSize: 12, color: 'var(--purple-7)', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon name="clock-circle" size={12} />
          체크포인트에서 재개됨 <code style={{ fontFamily: 'var(--font-family-code)' }}>{t.resumedFrom}</code>
        </div>
      ) : null}
      <Timeline
        items={(() => {
          // tools 라운드 순번(스펙 202/203 후속) — 다회 도구 루프의 카드 중복 귀속 방지.
          const toolsTotal = t.graph.filter((x) => x.node === 'tools').length
          let toolsSeen = 0
          return t.graph.map((n) => {
          const meta = nodeMeta(n.node)
          const tctx = n.node === 'tools'
            ? { summary: n.summary, toolsIdx: toolsSeen++, toolsTotal }
            : undefined
          const content = nodeEventContent(t, n.node, tctx)
          return {
            dot: <Icon name={meta.icon} size={13} style={{ color: meta.color }} />,
            children: (
              <div style={{ paddingBottom: 4 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)' }}>{meta.text}</span>
                  <span style={{ fontSize: 11, fontFamily: 'var(--font-family-code)', color: 'var(--color-text-quaternary)' }}>{n.node}</span>
                  <span style={{ fontSize: 11, color: 'var(--color-text-quaternary)', fontFamily: 'var(--font-family-code)' }}>
                    {n.parallel ? `병렬 ⏱${n.ms}ms` : `+${n.ms}ms`}
                  </span>
                </div>
                {n.summary ? (
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere', marginTop: 2 }}>
                    {n.summary}
                  </div>
                ) : null}
                {content ? <div style={{ marginTop: 6 }}>{content}</div> : null}
              </div>
            ),
          }
          })
        })()}
      />
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
  const [full, setFull] = useState(false)
  if (!agent) return null
  const t: Trace | undefined = turn && turn.role === 'ai' ? turn.trace : undefined
  const empty = !t

  // 프롬프트·설정 탭 — 턴 메타(전송 프롬프트·오버라이드). 노드 이벤트가 아니라 실행 흐름과 분리.
  const promptTab = t ? (
    <div style={{ padding: '4px 0' }}>
      {/* 전송 프롬프트(스펙 131) — 실제 LLM에 넣은 메시지 배열. user 입력은 채팅 버블서 이미 보여 제외. */}
      {t.sentMessages?.length ? (
        (() => {
          const shown = t.sentMessages.filter((m) => m.role !== 'user')
          return (
            <Section icon="file" iconColor="var(--color-primary)" title="전송 프롬프트" count={t.sentMessages.length}>
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
                {t.sentMessagesSource === 'measured'
                  ? `모델에 실제 전송된 메시지 ${t.sentMessages.length}개(마지막 호출 기준${t.modelCalls && t.modelCalls > 1 ? ` · 이 턴 모델 호출 ${t.modelCalls}회` : ''} · 메시지당 2000자 표시 상한).`
                  : `플랫폼 입력 기준 재구성 ${t.sentMessages.length}개(실측 미수집 턴 · 메시지당 2000자 표시 상한).`}{' '}
                user 입력 {t.sentMessages.length - shown.length}개는 채팅에서 확인 — 표시 생략.
              </div>
              <Collapse
                size="small"
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
      {/* 이 턴에 적용된 오버라이드(스펙 134). */}
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
      {/* RAG 컬렉션 가용성(호출 안 해도 배선됐는지) — 실행 흐름 밖 참고 정보. */}
      {(t.ragCollections?.length || t.ragUnresolved?.length) ? (
        <Section icon="database" iconColor="var(--geekblue-6)" title="연결된 문서 컬렉션" count={t.ragCollections?.length || 0}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(t.ragCollections ?? []).map((n) => (
              <Tag key={n} color="geekblue" style={{ whiteSpace: 'normal', height: 'auto', overflowWrap: 'anywhere' }}>{n}</Tag>
            ))}
          </div>
          {t.ragUnresolved?.length ? (
            <div style={{ fontSize: 12, color: 'var(--color-warning)', marginTop: 6, overflowWrap: 'anywhere' }}>
              ⚠ 미해석(임베딩 불완전): {t.ragUnresolved.join(', ')}
            </div>
          ) : null}
        </Section>
      ) : null}
      {/* 도구 무발동 진단(스펙 236) — 도구는 연결됐는데 이 턴 호출 0회면 "왜"를 표면화(조용한 무발동 금지).
          정보성 진단(도구와 무관한 질문일 수도) — 경고색이 아니라 보조 톤. */}
      {t.toolDiag ? (
        <Section icon="thunderbolt" iconColor="var(--cyan-7)" title="연결된 도구" count={t.toolDiag.bound.length}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {t.toolDiag.bound.map((n) => (
              <Tag key={n} color="cyan" style={{ whiteSpace: 'normal', height: 'auto', overflowWrap: 'anywhere' }}>{n}</Tag>
            ))}
          </div>
          {t.toolDiag.called === 0 && !t.brokerCalls?.length ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6, overflowWrap: 'anywhere' }}>
              이 턴에서 모델이 도구를 호출하지 않았습니다 — 질문이 도구와 무관했거나, 모델이 도구 호출을
              지원하지 않을 수 있습니다(mock 모델은 정해진 키워드·도구 이름을 문장에 쓸 때만 호출합니다).
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
              {t.toolDiag.called > 0
                ? `이 턴 도구 호출 ${t.toolDiag.called}회 — 상세는 실행 흐름 탭.`
                : '직접 도구 호출 0회 — 이 턴은 위임(브로커) 경유로 처리됐습니다(상세는 실행 흐름 탭).'}
            </div>
          )}
        </Section>
      ) : null}
    </div>
  ) : null

  // 인스펙터 본문(메트릭 + 탭) — 드로워와 전체화면 Modal이 공유.
  const body = t ? (
    <>
      <div style={{ display: 'flex', gap: 0, padding: '12px 16px', borderBottom: '1px solid var(--color-border-secondary)', alignItems: 'center' }}>
        <Metric label="지연시간" value={(t.latencyMs / 1000).toFixed(2) + 's'} />
        {/* 실행 버전(스펙 242/243) — 이 턴이 어느 버전 config였나. 미리보기(활성 아님)면 태그로 구분. */}
        {t.agentVersion && (
          <Metric
            label="버전"
            value={t.agentVersion + (t.versionPinned ? ' (미리보기)' : '')}
          />
        )}
        {/* 스펙 205 — 실측(usage)이면 그대로, 추정이면 ≈ 접두로 정직 표기. */}
        <Metric label={t.tokens.estimated ? '입력 토큰(추정)' : '입력 토큰'} value={(t.tokens.estimated ? '≈' : '') + t.tokens.in.toLocaleString()} />
        <Metric label={t.tokens.estimated ? '출력 토큰(추정)' : '출력 토큰'} value={(t.tokens.estimated ? '≈' : '') + t.tokens.out.toLocaleString()} />
      </div>
      <Tabs
        size="small"
        style={{ padding: '0 14px' }}
        items={[
          {
            key: 'flow',
            label: '실행 흐름',
            children: (
              <div style={{ padding: '8px 2px' }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
                  각 단계를 실행 순서대로 — 그 단계에서 무엇을 호출했고 결과가 어땠는지.
                </div>
                <NodeTimeline t={t} />
                {/* 도구 무발동 진단(스펙 236) — 무발동 턴은 흐름에 tools 노드가 아예 안 떠 조용하다.
                    "왜"를 찾는 곳이 이 기본 탭이므로 여기서 바로 안내(상세 목록은 프롬프트·설정 탭).
                    brokerCalls 있으면 억제 — 브로커 경유로 일한 턴을 "무발동"으로 오진 금지(codex 236 #2). */}
                {t.toolDiag && t.toolDiag.called === 0 && !t.brokerCalls?.length ? (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginTop: 12 }}
                    title={`도구 ${t.toolDiag.bound.length}개가 연결됐지만 이 턴에서 호출되지 않았습니다`}
                    description="질문이 도구와 무관했거나, 모델이 도구 호출을 지원하지 않을 수 있습니다. mock 모델은 정해진 키워드나 도구 이름을 문장에 쓸 때만 호출합니다. 연결 목록은 프롬프트·설정 탭에서 확인하세요."
                  />
                ) : null}
              </div>
            ),
          },
          { key: 'prompt', label: '프롬프트·설정', children: promptTab },
        ]}
      />
    </>
  ) : null

  return (
    <aside
      style={{
        // 폭은 부모(Splitter.Panel/Drawer)가 소유(스펙 204) — aside는 채우기만.
        width: '100%',
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
        {t && !fullWidth ? (
          <Button type="text" size="small" onClick={() => setFull(true)} title="전체화면으로 크게 보기">확대</Button>
        ) : null}
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
        <div style={{ flex: 1, overflowY: 'auto' }}>{full ? null : body}</div>
      )}

      {/* 전체화면 확대(스펙 192) — 드로워가 비좁을 때 넓은 오버레이로 깊게 디버깅. */}
      <Modal
        open={full}
        onCancel={() => setFull(false)}
        width="90vw"
        footer={null}
        title={`턴 인스펙터 — 턴 ${turnIndex + 1}`}
        styles={{ body: { maxHeight: '78vh', overflowY: 'auto' } }}
      >
        {full ? body : null}
      </Modal>
    </aside>
  )
}

