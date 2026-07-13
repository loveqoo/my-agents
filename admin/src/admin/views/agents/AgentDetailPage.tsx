/* 에이전트 상세 풀페이지(스펙 245→246 정보 3층 위계) — 1층=정체성·상태 배지(항상),
   2층=관심사 탭 **하나만 렌더**(구성/버전·배포/공개·연동/운영), 3층=상세·진단(빈 값 접기·식별자
   복사 강등). 개요 탭=요약 대시보드(각 관심사 한 줄+클릭 점프 — 지도이지 또 다른 상세가 아님).
   로컬(ui) 전용(code/external은 드로어 유지 — 후속). */
import { useEffect, useState } from 'react'
import { Tag, Button, Alert, Modal, Descriptions, Grid, Typography, Tooltip } from 'antd'
import { VersionHistory, ExposeSwitch } from '../../shared'
import { Icon } from '../../icons'
import { AgentMemoryPanel } from '../AgentMemoryPanel'
import { AGENT_STATUS, isOrchestratorImpl, isCodeDefinedImpl, isNodeRef, type Agent, type VersionMeta } from '../../mockData'
import { typeLabel } from './AgentForm'
import { DelegationGraph } from '../../DelegationGraph'
import { displayName } from '../../naming'
import { PersonaStaleNote } from './PersonaStaleNote'
import { FeedbackHarvestButton } from './FeedbackHarvestButton'
import { getAgentOps, listAgentImpls, type AgentOps, type ImplMeta } from '../../../api'
import { DetailPageShell, JumpCell, type DetailSection } from './detail/DetailPageShell'

function a2aCardUrl(agentPk: string): string {
  const env = (import.meta.env.VITE_API_BASE ?? '') as string
  const base = env || `${window.location.origin}/api`
  return `${base}/agents/${agentPk}/a2a/card`
}


export function AgentDetailPage({
  agent,
  agents,
  onBack,
  onEdit,
  onDelete,
  onClone,
  onToggleExpose,
  onSetVisibility,
  onActivate,
  onTest,
  onRevert,
  onNewDraft,
  onRefreshPersona,
}: {
  agent: Agent
  agents?: Agent[] // 위임 구조 조립용(스펙 257 — 전체 목록의 capabilities 그래프)
  onBack: () => void
  onEdit: (a: Agent) => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onSetVisibility: (a: Agent, pub: boolean) => void
  onActivate: (a: Agent, v: VersionMeta) => void
  onTest: (a: Agent, v: VersionMeta) => void
  onRevert: (a: Agent, v: VersionMeta) => void
  onNewDraft: (a: Agent) => void
  onRefreshPersona: (a: Agent) => Promise<void>
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  // 버전 운영 지표(스펙 244) — 관리 가능일 때만(서버 403 정합).
  const [ops, setOps] = useState<AgentOps | null>(null)
  useEffect(() => {
    setOps(null)
    if (agent.can_manage !== false && (agent.source || 'ui') === 'ui') {
      getAgentOps(agent.id).then(setOps).catch(() => setOps(null))
    }
  }, [agent.id, agent.can_manage])

  // 실행 방식 소비 표면(스펙 206) — 폼과 같은 단일 출처(consumes). 안 읽는 표면의 행은
  // 상세에서도 두지 않는다(예: 조율형은 도구·문서 미소비 — 노드형 행 제거와 같은 원칙, 2026-07-10).
  // 미선언(null)·로드 실패=전부 노출(무회귀, 폼과 동일 best-effort).
  const [implMetas, setImplMetas] = useState<Record<string, string[] | null>>({})
  useEffect(() => {
    listAgentImpls()
      .then((ms: ImplMeta[]) => setImplMetas(Object.fromEntries(ms.map((m) => [m.key, m.consumes]))))
      .catch(() => {})
  }, [])
  const consumes = agent.impl ? (implMetas[agent.impl] ?? null) : null
  const consumed = (surface: string) => consumes == null || consumes.includes(surface)

  const draft = (agent.versions || []).find((v) => v.status === 'draft')
  // 코드 정의 impl(스펙 327) — **구성 편집만** 봉인(구성은 코드가 소유, 원격 code와 같은 원칙).
  // 삭제·공개 전환·활성화·운영은 인스턴스 관리라 소유권(canManage) 기준 그대로 — 목록(AgentsView)의
  // 삭제 버튼 정책과 정합(codex 327: 두 축을 canManage 하나로 합치면 상세만 과봉인돼 비일관).
  const codeDefined = isCodeDefinedImpl(agent.impl)
  const canManage = agent.can_manage !== false
  const canEdit = canManage && !codeDefined
  // 종류 라벨 — AgentForm typeLabel 단일 출처(스펙 283/286). 로컬 사본은 pipeline 등
  // AGENT_TYPES 신설 키를 놓쳐 내부 키를 그대로 노출했다(스펙 108 위반).
  const kindLabel = typeLabel(agent.impl)

  const sections: DetailSection[] = [
    {
      key: 'overview',
      label: '개요',
      render: (jump) => (
          <section>
            {/* key/value 표(사용자 제안) — bordered Descriptions로 레이블 셀/값 셀 구분. 점프는 값 셀 클릭. */}
            <Descriptions
              column={1}
              size="small"
              bordered
              layout={isMobile ? 'vertical' : 'horizontal'}
              labelStyle={{ width: 120 }}
              items={[
                {
                  key: 'run',
                  label: '실행',
                  children: (
                    // 모델·활성 세션만(스펙 286 후속 — 페르소나는 구성 탭이 소유).
                    // 노드형은 모델이 노드마다 달라 대표 모델 표기가 거짓(2026-07-10) — 노드 흐름으로 대체.
                    <span>
                      {agent.impl === 'pipeline' ? (
                        <span>
                          {/* 참조 노드(스펙 316)는 이름을 라이브러리가 소유 — name@version으로 표기. */}
                          {(agent.nodes || [])
                            .map((n, i) => (isNodeRef(n) ? `${n.ref.name}@v${n.ref.version}` : n.name?.trim() || `노드 ${i + 1}`))
                            .join(' → ') || '노드 없음'}
                        </span>
                      ) : (
                        <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>
                      )}
                      <span style={{ color: 'var(--color-text-tertiary)' }}> · 활성 세션 {agent.sessions ?? 0}개</span>
                    </span>
                  ),
                },
                {
                  key: 'config',
                  label: '구성',
                  children: (
                    <JumpCell onJump={() => jump('config')}>
                      {(() => {
                        const parts: string[] = []
                        // 노드형은 도구·프롬프트가 노드 소유 — 노드 수가 구성 요약(스펙 286).
                        // 그 외는 consumes(스펙 206)가 안 읽는 표면 카운트 제외(구성 탭 행과 같은 게이트).
                        if (agent.impl === 'pipeline') {
                          if ((agent.nodes || []).length) parts.push(`노드 ${(agent.nodes || []).length}개`)
                        } else if (consumed('mcps') && (agent.tools || []).length) {
                          // 276 이후 진실원=tools(도구 단위). mcps는 서버 합집합 파생이라 카운트 부정확.
                          parts.push(`도구 ${(agent.tools || []).length}개`)
                        } else if (consumed('mcps') && (agent.mcps || []).length) {
                          parts.push(`도구 서버 ${agent.mcps.length}개(전체)`)
                        }
                        if (agent.impl !== 'pipeline' && consumed('vectorTables') && (agent.vectorTables || []).length) parts.push(`문서 ${agent.vectorTables.length}개`)
                        { const liveMem = (agent.memories || []); if (agent.impl !== 'pipeline' && consumed('memories') && liveMem.length) parts.push(`기억 ${liveMem.length}개`) }
                        // 위임 대상은 수만으론 빈약(사용자 지적) — 이름으로(agents 목록에서 해석).
                        const caps = agent.capabilities || []
                        if (caps.length) {
                          const names = caps.map((c) => {
                            if (c.includes(':')) return c // mcp:/rag: 능력은 키 그대로
                            const hit = (agents || []).find((x) => x.agentId === c)
                            return hit ? displayName(hit) : c
                          })
                          parts.push(`위임 대상 ${caps.length}개 — ${names.slice(0, 3).join(', ')}${caps.length > 3 ? ` 외 ${caps.length - 3}개` : ''}`)
                        }
                        return parts.length ? parts.join(' · ') : '연결 없음 — 모델만으로 응답'
                      })()}
                    </JumpCell>
                  ),
                },
                {
                  key: 'versions',
                  label: '버전·배포',
                  children: (
                    <JumpCell onJump={() => jump('versions')}>
                      {/* `vN · 상태` 압축(스펙 286 후속) — 설명형 문장은 버전 탭이 소유. */}
                      {agent.activeVersion
                        ? `${agent.activeVersion} · 서빙 중${draft ? ` · 초안 ${draft.version} 대기` : ''}`
                        : draft
                        ? `${draft.version} · 미서빙`
                        : '버전 없음'}
                    </JumpCell>
                  ),
                },
                {
                  key: 'sharing',
                  label: '공개·연동',
                  children: (
                    <JumpCell onJump={() => jump('sharing')}>
                      {/* 압축 표기(스펙 286 후속) — 설명은 공개·연동 탭이 소유. A2A는 상태 점. */}
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        {agent.owner_id == null ? '공개' : '비공개'}
                        <span style={{ color: 'var(--color-text-quaternary)' }}>·</span>
                        <Tooltip title={agent.exposed?.a2a ? 'A2A 켬 — 다른 에이전트가 호출 가능' : 'A2A 꺼짐 — 노출되지 않음'}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                            <span aria-label={agent.exposed?.a2a ? 'A2A 켬' : 'A2A 꺼짐'} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: agent.exposed?.a2a ? 'var(--green-6)' : 'var(--gray-5)' }} />
                            A2A
                          </span>
                        </Tooltip>
                      </span>
                    </JumpCell>
                  ),
                },
                {
                  key: 'ops',
                  label: '운영',
                  children: (
                    <JumpCell onJump={() => jump('operations')}>
                      {(() => {
                        if (!ops) return '피드백 없음'
                        const vs = Object.values(ops.versions || {})
                        const up = vs.reduce((n, v) => n + v.up, 0) + ops.unversionedUp
                        const down = vs.reduce((n, v) => n + v.down, 0) + ops.unversionedDown
                        const cur = agent.activeVersion ? ops.versions?.[agent.activeVersion] : undefined
                        const score = cur?.lastScore != null ? ` · 최근 평가 ${Math.round(cur.lastScore * 100)}%` : ''
                        return (up || down || score) ? `👍${up} 👎${down}${score}` : '피드백 없음'
                      })()}
                    </JumpCell>
                  ),
                },
              ]}
            />
            {(agent.environments || []).length > 0 && (
              <div style={{ display: 'flex', gap: 4, marginTop: 10 }}>
                {(agent.environments || []).map((env) =>
                  env === 'production' ? <Tag key={env} color="geekblue">{env}</Tag> : <Tag key={env}>{env}</Tag>
                )}
              </div>
            )}
            <PersonaStaleNote agent={agent} onRefresh={onRefreshPersona} />
          </section>
      ),
    },
    {
      key: 'config',
      label: '구성',
      render: () => (
          <section>
            <Descriptions
              column={1}
              size="small"
              bordered
              layout={isMobile ? 'vertical' : 'horizontal'}
              labelStyle={{ width: 120 }}
              items={[
                // 노드형은 모델·페르소나도 노드 소유(실행=노드별 model_cfg, 최상위 persona 미참조 —
                // pipeline.py) — 행 자체를 두지 않는다(2026-07-10). 노드별 모델은 아래 "노드" 행이 표시.
                ...(agent.impl !== 'pipeline'
                  ? [
                      { key: 'model', label: '모델', children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span> },
                      { key: 'persona', label: '페르소나', children: agent.persona || '없음' },
                    ]
                  : []),
                {
                  key: 'history',
                  label: '단기 기억',
                  children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
                },
                // 상설 행 + 값 '없음'(스펙 286 후속, 사용자 지시) — "연결 없음: …" 각주 대체.
                // 노드형은 장기 기억·문서·도구가 노드 소유(259)라 에이전트 수준 행 자체를 두지 않고,
                // 그 외 impl은 consumes 선언(스펙 206)이 안 읽는 표면의 행도 두지 않는다(예: 조율형=도구·문서 미소비).
                // 장기 기억(mem0) 태그만 표시 — 단기는 위 "단기 기억"(historyDepth)이 소유.
                ...(agent.impl !== 'pipeline' && consumed('memories')
                  ? [
                      {
                        key: 'memories',
                        label: '장기 기억',
                        children: (agent.memories || []).length ? (
                          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                            {agent.memories.map((m) => <Tag key={m} color="purple">{m}</Tag>)}
                          </span>
                        ) : (
                          '없음'
                        ),
                      },
                    ]
                  : []),
                ...(agent.impl !== 'pipeline' && consumed('vectorTables')
                  ? [
                      {
                        key: 'vectors',
                        label: '문서',
                        children: (agent.vectorTables || []).length ? (
                          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                            {agent.vectorTables.map((t) => (
                              <Tag key={t} color="cyan"><code style={{ fontFamily: 'var(--font-family-code)' }}>{t}</code></Tag>
                            ))}
                          </span>
                        ) : (
                          '없음'
                        ),
                      },
                    ]
                  : []),
                // 도구(스펙 276/286) — tools(도구 단위 배선)가 진실원. 빈 tools+mcps=서버 전체
                // 폴백을 정직 표기. 라벨은 폼과 같은 사용자 어휘('도구' — MCP는 내부어).
                ...(agent.impl !== 'pipeline' && consumed('mcps')
                  ? [
                      {
                        key: 'tools',
                        label: '도구',
                        children: (agent.tools || []).length ? (
                          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                            {(agent.tools || []).map((rt) => {
                              const [srv, ...rest] = rt.split('__')
                              return <Tag key={rt} color="cyan">{srv} · {rest.join('__') || rt}</Tag>
                            })}
                          </span>
                        ) : (agent.mcps || []).length ? (
                          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                            {agent.mcps.map((m) => <Tag key={m} color="cyan">{m}</Tag>)}
                            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>서버의 모든 도구 사용</span>
                          </span>
                        ) : (
                          '없음'
                        ),
                      },
                    ]
                  : []),
                // 노드형 파이프라인 요약(스펙 286) — 노드 이름(모델)을 실행 순서대로.
                ...(agent.impl === 'pipeline' && (agent.nodes || []).length
                  ? [{
                      key: 'nodes',
                      label: '노드',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
                          {(agent.nodes || []).map((n, i) => {
                            // 참조 노드(스펙 316): 라벨=name@version, 모델은 해석 파생(resolvedNodes,
                            // 인덱스 정렬 일치)에서 — 미해결이면 모델 미표기(거짓 표기 금지).
                            const label = isNodeRef(n) ? `${n.ref.name}@v${n.ref.version}` : n.name?.trim() || `노드 ${i + 1}`
                            const model = isNodeRef(n) ? agent.resolvedNodes?.[i]?.model : n.model
                            return (
                              <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                {i > 0 && <Icon name="right" size={10} style={{ color: 'var(--color-text-quaternary)' }} />}
                                <Tag style={{ margin: 0 }}>
                                  {label}
                                  {model ? <span style={{ color: 'var(--color-text-tertiary)' }}> · {model}</span> : null}
                                </Tag>
                              </span>
                            )
                          })}
                        </span>
                      ),
                    }]
                  : []),
                // "위임 대상" raw id 행 제거(스펙 257) — 아래 위임 구조 그래프가 canonical(이름·
                // 계층·순환까지). 에이전트 외 능력(mcp:/rag:)만 남긴다.
                ...((agent.capabilities || []).filter((c) => c.includes(':')).length
                  ? [{
                      key: 'caps',
                      label: '위임 능력',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {(agent.capabilities || []).filter((c) => c.includes(':')).map((c) => <Tag key={c} color="geekblue">{c}</Tag>)}
                        </span>
                      ),
                    }]
                  : []),
              ]}
            />
            {/* "연결 없음: …" 각주는 상설 행+'없음' 값으로 대체(스펙 286 후속, 사용자 지시). */}
            {/* 위임 구조(스펙 257) — 조율형이면 누구에게 맡길 수 있고 그 아래가 어떻게 이어지는지.
                설정상 순환은 빨간 마커(실행 시 자동 차단 — 256 v2 체인)로 정직 표시. */}
            {isOrchestratorImpl(agent.impl) && agents ? (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>위임 구조</div>
                <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)', padding: '10px 14px' }}>
                  <DelegationGraph rootAgentId={agent.agentId} agents={agents} />
                </div>
              </div>
            ) : null}
            {/* 에이전트 지식(mem0) — 내부에 탭·검색·목록을 가진 복합 위젯이라 Descriptions 값 칸에
                넣으면 모바일(360px)에서 레이블 옆 셀로 밀려 우측이 뚫린다(사용자 신고) → 전체폭 블록. */}
            {(agent.memories || []).includes('장기 기억 (mem0)') && (agent.source || 'ui') === 'ui' && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
                  에이전트 지식 (mem0)
                </div>
                <AgentMemoryPanel agentId={agent.id} />
              </div>
            )}
          </section>
      ),
    },
    {
      key: 'versions',
      label: '버전·배포',
      render: () => (
          <section>
            {draft ? (
              <div style={{ marginBottom: 14, border: '1px solid var(--gold-3)', background: 'var(--gold-1)', borderRadius: 'var(--radius-lg)', padding: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Tag color="gold">초안 {draft.version}</Tag>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', flex: 1 }}>{draft.note}</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 12 }}>
                  {draft.config
                    ? (() => {
                        const cfg = draft.config
                        const diffs: string[] = []
                        if (cfg.model !== agent.model) diffs.push('모델 → ' + cfg.model)
                        if (cfg.persona !== agent.persona) diffs.push('페르소나 → ' + cfg.persona)
                        if ((cfg.memories || []).join() !== (agent.memories || []).join()) diffs.push('장기 기억 변경됨')
                        if (cfg.historyDepth !== agent.historyDepth) diffs.push('단기 기억 → ' + (cfg.historyDepth || 0))
                        if ((cfg.vectorTables || []).join() !== (agent.vectorTables || []).join()) diffs.push('문서 변경됨')
                        // 도구는 tools(276 도구 단위)와 mcps(파생) 어느 쪽이 달라도 한 번만 보고.
                        if ((cfg.tools || []).join() !== (agent.tools || []).join() || (cfg.mcps || []).join() !== (agent.mcps || []).join()) diffs.push('도구 변경됨')
                        return diffs.length ? (
                          diffs.map((d, i) => <Tag key={i} color="geekblue">{d}</Tag>)
                        ) : (
                          <span style={{ color: 'var(--color-text-tertiary)' }}>활성 버전과 동일 — 편집해 변경하세요.</span>
                        )
                      })()
                    : null}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
                  {canEdit && (
                    <Button size="small" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>편집</Button>
                  )}
                  <Button size="small" type="primary" icon={<Icon name="thunderbolt" />} onClick={() => onTest(agent, draft)}>
                    테스트
                  </Button>
                  {canManage && (
                    <Button size="small" icon={<Icon name="check" />} onClick={() => onActivate(agent, draft)}>활성화</Button>
                  )}
                </div>
              </div>
            ) : null}
            <VersionHistory
              versions={agent.versions || []}
              onActivate={(v) => onActivate(agent, v)}
              onTest={(v) => onTest(agent, v)}
              onRevert={(v) => onRevert(agent, v)}
              onNewDraft={draft ? null : () => onNewDraft(agent)}
              ops={ops?.versions}
            />
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
              편집은 항상 초안에 저장됩니다 — 활성 버전은 계속 서빙. 초안을 테스트한 뒤 활성화해 게시하세요.
            </div>
          </section>
      ),
    },
    {
      key: 'sharing',
      label: '공개·연동',
      render: () => (
          <section>
            {/* key/value 표(사용자 제안) — 흩어진 박스 3개를 한 표로. 행=공개 범위/A2A/식별자(조건). */}
            <Descriptions
              column={1}
              size="small"
              bordered
              layout={isMobile ? 'vertical' : 'horizontal'}
              labelStyle={{ width: 120 }}
              items={[
                {
                  key: 'visibility',
                  label: '공개 범위',
                  children: (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      {/* 값은 상태만(사용자 지시) — A2A 제약은 A2A 행이, 의미 설명은 전환 모달이 소유. */}
                      <span style={{ flex: 1, minWidth: 180 }}>
                        {agent.owner_id == null ? '공개' : '비공개'}
                      </span>
                      {canManage && (
                        <Button
                          size="small"
                          onClick={() =>
                            Modal.confirm({
                              title: agent.owner_id == null ? '비공개로 전환할까요?' : '공개로 전환할까요?',
                              content:
                                agent.owner_id == null
                                  ? '비공개가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                                  : '공개가 되면 모든 사용자가 이 에이전트를 도구처럼 사용할 수 있고 A2A 공개도 켤 수 있게 됩니다.',
                              okText: '전환',
                              cancelText: '취소',
                              onOk: () => onSetVisibility(agent, agent.owner_id != null),
                            })
                          }
                        >
                          {agent.owner_id == null ? '비공개로 전환' : '공개로 전환'}
                        </Button>
                      )}
                    </span>
                  ),
                },
                {
                  key: 'a2a',
                  // 라벨은 'A2A'만(사용자 지시) — 공개/비공개는 스위치 상태가 말한다.
                  label: 'A2A',
                  children: (
                    <ExposeSwitch
                      on={!!agent.exposed.a2a}
                      onChange={() => onToggleExpose(agent)}
                      label=""
                      onText="켬 · 다른 에이전트가 호출 가능"
                      offText={agent.owner_id != null ? '공개로 전환하면 켤 수 있습니다' : '꺼짐 · 노출되지 않음'}
                      disabled={agent.owner_id != null}
                    />
                  ),
                },
                ...(agent.exposed.a2a
                  ? [
                      {
                        key: 'aid',
                        label: 'Agent ID',
                        children: (
                          <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            <Typography.Text code copyable={{ text: agent.agentId, tooltips: ['복사', '복사됨'] }} style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}>
                              {agent.agentId}
                            </Typography.Text>
                            <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>불변 · 모든 환경에서 동일한 ID</span>
                          </span>
                        ),
                      },
                      {
                        key: 'card',
                        label: 'A2A 카드',
                        children: (
                          <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            <Typography.Text code copyable={{ text: a2aCardUrl(agent.id), tooltips: ['복사', '복사됨'] }} ellipsis style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, maxWidth: '100%' }}>
                              {a2aCardUrl(agent.id)}
                            </Typography.Text>
                            <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
                              이 URL을 <strong>“원격 에이전트 연결”</strong>에 붙여 등록·테스트. 루프백/사설 주소면 백엔드에{' '}
                              <code style={{ fontFamily: 'var(--font-family-code)' }}>A2A_ALLOWED_HOSTS=127.0.0.1</code> 필요.
                            </span>
                          </span>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </section>
      ),
    },
    {
      key: 'operations',
      label: '운영',
      render: (jump) => (
          <section>
            {canManage ? (
              <Descriptions
                column={1}
                size="small"
                bordered
                layout={isMobile ? 'vertical' : 'horizontal'}
                labelStyle={{ width: 120 }}
                items={[
                  {
                    key: 'harvest',
                    label: '피드백 수확',
                    children: (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span style={{ flex: 1, minWidth: 180, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                          응답 피드백을 초안 평가 케이스로 — 에이전트 변경 회귀 지표
                        </span>
                        <FeedbackHarvestButton agentId={agent.id} />
                      </span>
                    ),
                  },
                  ...(ops && (ops.unversionedUp > 0 || ops.unversionedDown > 0)
                    ? [{
                        key: 'unversioned',
                        label: '버전 미기록',
                        children: (
                          // 찬반 내역은 여기선 무의미(사용자 지적) — 이 행의 역할은 "집계 밖 피드백이
                          // 있다"는 정직성 고지뿐이라 합계 건수만.
                          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                            피드백 {ops.unversionedUp + ops.unversionedDown}건 — 버전 기록 도입 전 대화(버전별 집계 제외)
                          </span>
                        ),
                      }]
                    : []),
                ]}
              />
            ) : (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>운영 도구는 관리 권한이 필요합니다.</span>
            )}
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
              버전별 성적·피드백은 <a onClick={() => jump('versions')}>버전·배포</a> 탭의 이력 행에 표시됩니다.
            </div>
          </section>
      ),
    },
  ]

  return (
    <DetailPageShell
      onBack={onBack}
      avatar={<Icon name="robot" />}
      name={displayName(agent)}
      agentId={agent.agentId}
      badges={
        <>
          {/* 배지 슬림화(스펙 286, 284 계승) — 신호등(상태)+종류+예외 태그만. 공개 범위·A2A·
              초안·서빙 버전은 각 탭/개요 행이 소유(중복 태그 제거). */}
          {agent.conformance === 'config_error' ? (
            <Tag color="red" style={{ margin: 0 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
                <Icon name="exclamation-circle" size={11} /> 설정 실패
              </span>
            </Tag>
          ) : (() => {
            const st = AGENT_STATUS[agent.status] ?? AGENT_STATUS.offline
            return (
              <Tooltip title={st.desc}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--color-text-secondary)' }}>
                  <span aria-label={st.label} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: st.color }} />
                  {st.label}
                </span>
              </Tooltip>
            )
          })()}
          <Tag style={{ margin: 0 }}>{kindLabel}</Tag>
          {agent.ephemeral && <Tag color="orange" style={{ margin: 0 }}>비영속</Tag>}
        </>
      }
      actions={
        <>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {canManage && (
            <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
              삭제
            </Button>
          )}
          {canEdit ? (
            <Button type="primary" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
              {draft ? '초안 편집' : '편집(새 초안)'}
            </Button>
          ) : (
            <span style={{ color: 'var(--color-text-tertiary)', alignSelf: 'center' }}>
              {canManage ? '코드 정의 — 구성은 코드가 소유' : '다른 사용자 소유 — 관리 권한 없음'}
            </span>
          )}
        </>
      }
      aboveTabs={
        agent.conformance === 'config_error' ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            title="에이전트 설정 실패 — 런타임이 서빙을 거부합니다"
            description="이 에이전트는 실행 방식 설정에 문제가 있어 실행할 수 없습니다(등록되지 않았거나 형식이 맞지 않음). 담당자에게 문의하거나, 실행 방식을 기본값으로 되돌린 뒤 다시 시도하세요."
          />
        ) : codeDefined ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title="코드 정의 에이전트 — 구성은 코드가 소유합니다"
            description="이 에이전트의 실행 방식은 코드(SDK 또는 스킬 코드젠)로 정의되어 있습니다. 수정은 코드에서 하고, 동작 확인은 플레이그라운드에서 할 수 있습니다."
          />
        ) : null
      }
      sections={sections}
    />
  )
}


