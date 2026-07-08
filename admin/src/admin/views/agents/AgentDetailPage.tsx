/* 에이전트 상세 풀페이지(스펙 245→246 정보 3층 위계) — 1층=정체성·상태 배지(항상),
   2층=관심사 탭 **하나만 렌더**(구성/버전·배포/공개·연동/운영), 3층=상세·진단(빈 값 접기·식별자
   복사 강등). 개요 탭=요약 대시보드(각 관심사 한 줄+클릭 점프 — 지도이지 또 다른 상세가 아님).
   로컬(ui) 전용(code/external은 드로어 유지 — 후속). */
import { useEffect, useRef, useState } from 'react'
import { Tag, Button, Avatar, Alert, Modal, Descriptions, Grid, Tooltip, message, Typography } from 'antd'
import { VersionHistory, ExposeSwitch } from '../../shared'
import { Icon } from '../../icons'
import { AgentMemoryPanel } from '../AgentMemoryPanel'
import { isOrchestratorImpl, type Agent, type VersionMeta } from '../../mockData'
import { displayName } from '../../naming'
import { PersonaStaleNote } from './PersonaStaleNote'
import { FeedbackHarvestButton } from './FeedbackHarvestButton'
import { getAgentOps, type AgentOps } from '../../../api'

function a2aCardUrl(agentPk: string): string {
  const env = (import.meta.env.VITE_API_BASE ?? '') as string
  const base = env || `${window.location.origin}/api`
  return `${base}/agents/${agentPk}/a2a/card`
}

const SECTIONS = [
  { key: 'overview', label: '개요' },
  { key: 'config', label: '구성' },
  { key: 'versions', label: '버전·배포' },
  { key: 'sharing', label: '공개·연동' },
  { key: 'operations', label: '운영' },
] as const

export function AgentDetailPage({
  agent,
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
  const bodyRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState<string>('overview')

  // 버전 운영 지표(스펙 244) — 관리 가능일 때만(서버 403 정합).
  const [ops, setOps] = useState<AgentOps | null>(null)
  useEffect(() => {
    setOps(null)
    if (agent.can_manage !== false && (agent.source || 'ui') === 'ui') {
      getAgentOps(agent.id).then(setOps).catch(() => setOps(null))
    }
  }, [agent.id, agent.can_manage])

  // 2층=탭(스펙 246): 하나만 렌더 — 화면 정보량이 항상 "지금 하는 일" 분량.
  const jump = (key: string) => {
    setActive(key)
    bodyRef.current?.scrollIntoView({ block: 'start' })
  }

  const draft = (agent.versions || []).find((v) => v.status === 'draft')
  const canManage = agent.can_manage !== false
  // 종류 라벨(사용자 언어, 스펙 108과 동일 매핑)
  const typeLabel = !agent.impl ? '직접 응답' : agent.impl.startsWith('artifact') ? '산출물형' : isOrchestratorImpl(agent.impl) ? '조율형' : agent.impl

  const nav = (
    <div
      style={
        isMobile
          ? { display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 8 }
          : { display: 'flex', flexDirection: 'column', gap: 2, position: 'sticky', top: 12, minWidth: 120 }
      }
    >
      {SECTIONS.map((s) => (
        <Button
          key={s.key}
          type={active === s.key ? 'primary' : 'text'}
          size="small"
          style={{ justifyContent: 'flex-start', flexShrink: 0 }}
          onClick={() => jump(s.key)}
        >
          {s.label}
        </Button>
      ))}
    </div>
  )

  return (
    // 중앙 정렬 컨테이너(사용자 피드백) — 좌측 네비+본문이 왼쪽에 붙으면 넓은 화면서 우측이 통째로
    // 비어 쏠려 보인다. 문서처럼 가운데(최대 1040px)로.
    <div style={{ maxWidth: 1040, margin: '0 auto', width: '100%' }}>
      {/* 상단(사용자 피드백: 목록 버튼이 정체성 줄에 끼어 어수선) — 1줄=돌아가기, 2줄=정체성|액션. */}
      <div style={{ marginBottom: 10 }}>
        <Button type="text" size="small" icon={<Icon name="arrow-left" size={12} />} onClick={onBack} style={{ color: 'var(--color-text-tertiary)', paddingInline: 4 }}>
          에이전트 목록
        </Button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Avatar size="large" style={{ background: 'var(--gray-12)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 16, fontWeight: 600 }}>{displayName(agent)}</span>
            {/* 식별자 강등(스펙 246 3층) — 본문 코드 대신 복사 버튼+툴팁. canonical 표기는 공개·연동 탭. */}
            <Tooltip title={<span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.agentId}</span>}>
              <Button
                type="text"
                size="small"
                icon={<Icon name="copy" size={12} />}
                onClick={() => {
                  void navigator.clipboard.writeText(agent.agentId)
                  message.success('Agent ID 복사됨')
                }}
              />
            </Tooltip>
          </div>
          {/* 1층 상태 배지(스펙 246) — 정체성·상태를 한 줄로(각 탭 상세의 요약이 아니라 상태 신호만). */}
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 2 }}>
            {agent.conformance === 'config_error' ? (
              <Tag color="red" style={{ margin: 0 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
                  <Icon name="exclamation-circle" size={11} /> 설정 실패
                </span>
              </Tag>
            ) : agent.activeVersion ? (
              <Tag color="green" style={{ margin: 0 }}>서빙 {agent.activeVersion}</Tag>
            ) : (
              <Tag style={{ margin: 0 }}>미서빙 · 초안만</Tag>
            )}
            <Tag style={{ margin: 0 }}>{typeLabel}</Tag>
            {draft && <Tag color="gold" style={{ margin: 0 }}>초안 {draft.version}</Tag>}
            <Tag style={{ margin: 0 }}>{agent.owner_id == null ? 'public' : 'private'}</Tag>
            {agent.exposed?.a2a && <Tag color="green" style={{ margin: 0 }}>A2A</Tag>}
            {agent.ephemeral && <Tag color="orange" style={{ margin: 0 }}>비영속</Tag>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {canManage ? (
            <>
              <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
                삭제
              </Button>
              <Button type="primary" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
                {draft ? '초안 편집' : '편집(새 초안)'}
              </Button>
            </>
          ) : (
            <span style={{ color: 'var(--color-text-tertiary)', alignSelf: 'center' }}>다른 사용자 소유 — 관리 권한 없음</span>
          )}
        </div>
      </div>

      {agent.conformance === 'config_error' ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title="에이전트 설정 실패 — 런타임이 서빙을 거부합니다"
          description="이 에이전트는 실행 방식 설정에 문제가 있어 실행할 수 없습니다(등록되지 않았거나 형식이 맞지 않음). 담당자에게 문의하거나, 실행 방식을 기본값으로 되돌린 뒤 다시 시도하세요."
        />
      ) : null}

      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 24 }}>
        {nav}
        <div ref={bodyRef} style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* ── 개요(스펙 246) — 요약 대시보드: 각 관심사의 한 줄 요약 + 클릭 점프(지도). ── */}
          {active === 'overview' && (
          <section>
            <SectionTitle>개요 — 한눈에</SectionTitle>
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
                    <span>
                      <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>
                      <span style={{ color: 'var(--color-text-tertiary)' }}> · 페르소나 {agent.persona || '없음'} · 활성 세션 {agent.sessions ?? 0}개</span>
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
                        if ((agent.mcps || []).length) parts.push(`도구 ${agent.mcps.length}`)
                        if ((agent.vectorTables || []).length) parts.push(`문서 ${agent.vectorTables.length}`)
                        if ((agent.memories || []).length) parts.push(`메모리 ${agent.memories.length}`)
                        if ((agent.capabilities || []).length) parts.push(`위임 대상 ${(agent.capabilities || []).length}`)
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
                      {agent.activeVersion ? `서빙 ${agent.activeVersion}` : '미서빙(초안만 — 활성화 필요)'}
                      {draft ? ` · 초안 ${draft.version} 대기 중` : agent.activeVersion ? ' · 초안 없음' : ''}
                    </JumpCell>
                  ),
                },
                {
                  key: 'sharing',
                  label: '공개·연동',
                  children: (
                    <JumpCell onJump={() => jump('sharing')}>
                      {agent.owner_id == null ? 'public(모두 사용 가능)' : 'private(소유자만)'} · A2A {agent.exposed?.a2a ? '켬' : '꺼짐'}
                    </JumpCell>
                  ),
                },
                {
                  key: 'ops',
                  label: '운영',
                  children: (
                    <JumpCell onJump={() => jump('operations')}>
                      {(() => {
                        if (!ops) return '지표 없음'
                        const vs = Object.values(ops.versions || {})
                        const up = vs.reduce((n, v) => n + v.up, 0) + ops.unversionedUp
                        const down = vs.reduce((n, v) => n + v.down, 0) + ops.unversionedDown
                        const cur = agent.activeVersion ? ops.versions?.[agent.activeVersion] : undefined
                        const score = cur?.lastScore != null ? ` · 최근 평가 ${Math.round(cur.lastScore * 100)}%` : ''
                        return (up || down || score) ? `👍${up} 👎${down}${score}` : '지표 없음'
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
          )}

          {/* ── 구성(스펙 246) — 값 있는 표면만 행으로, 없는 것은 한 줄로 접기(빈 값도 자리 차지 금지). ── */}
          {active === 'config' && (
          <section>
            <SectionTitle>구성 — 무엇을 쓸 수 있나</SectionTitle>
            <Descriptions
              column={1}
              size="small"
              bordered
              layout={isMobile ? 'vertical' : 'horizontal'}
              labelStyle={{ width: 120 }}
              items={[
                { key: 'model', label: '모델', children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span> },
                { key: 'persona', label: '페르소나', children: agent.persona || '없음' },
                {
                  key: 'history',
                  label: '채팅 히스토리',
                  children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
                },
                ...((agent.memories || []).length
                  ? [{
                      key: 'memories',
                      label: '메모리',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {agent.memories.map((m) => <Tag key={m} color="purple">{m}</Tag>)}
                        </span>
                      ),
                    }]
                  : []),
                ...((agent.vectorTables || []).length
                  ? [{
                      key: 'vectors',
                      label: '벡터 테이블',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {agent.vectorTables.map((t) => (
                            <Tag key={t} color="cyan"><code style={{ fontFamily: 'var(--font-family-code)' }}>{t}</code></Tag>
                          ))}
                        </span>
                      ),
                    }]
                  : []),
                ...((agent.mcps || []).length
                  ? [{
                      key: 'mcps',
                      label: 'MCP',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {agent.mcps.map((m) => <Tag key={m} color="cyan">{m}</Tag>)}
                        </span>
                      ),
                    }]
                  : []),
                ...((agent.capabilities || []).length
                  ? [{
                      key: 'caps',
                      label: '위임 대상',
                      children: (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {(agent.capabilities || []).map((c) => <Tag key={c} color="geekblue">{c}</Tag>)}
                        </span>
                      ),
                    }]
                  : []),
              ]}
            />
            {(() => {
              const empty: string[] = []
              if (!(agent.memories || []).length) empty.push('메모리')
              if (!(agent.vectorTables || []).length) empty.push('문서(벡터)')
              if (!(agent.mcps || []).length) empty.push('도구(MCP)')
              return empty.length ? (
                <div style={{ fontSize: 12, color: 'var(--color-text-quaternary)', marginTop: 8 }}>
                  연결 없음: {empty.join(' · ')}
                </div>
              ) : null
            })()}
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
          )}

          {/* ── 버전·배포 ── */}
          {active === 'versions' && (
          <section>
            <SectionTitle>버전·배포 — 바꾸고 내보내기</SectionTitle>
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
                        if ((cfg.memories || []).join() !== (agent.memories || []).join()) diffs.push('메모리 변경됨')
                        if (cfg.historyDepth !== agent.historyDepth) diffs.push('채팅 히스토리 → ' + (cfg.historyDepth || 0))
                        if ((cfg.vectorTables || []).join() !== (agent.vectorTables || []).join()) diffs.push('벡터 테이블 변경됨')
                        if ((cfg.mcps || []).join() !== (agent.mcps || []).join()) diffs.push('MCP 변경됨')
                        return diffs.length ? (
                          diffs.map((d, i) => <Tag key={i} color="geekblue">{d}</Tag>)
                        ) : (
                          <span style={{ color: 'var(--color-text-tertiary)' }}>활성 버전과 동일 — 편집해 변경하세요.</span>
                        )
                      })()
                    : null}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
                  {canManage && (
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
          )}

          {/* ── 공개·연동 ── */}
          {active === 'sharing' && (
          <section>
            <SectionTitle>공개·연동 — 누가 쓸 수 있나</SectionTitle>
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
                      <span style={{ flex: 1, minWidth: 180 }}>
                        {agent.owner_id == null
                          ? 'public · 모두 도구처럼 사용 가능(A2A 켜기 가능)'
                          : 'private · 소유자만 사용(A2A 불가)'}
                      </span>
                      {canManage && (
                        <Button
                          size="small"
                          onClick={() =>
                            Modal.confirm({
                              title: agent.owner_id == null ? '비공개(private)로 전환할까요?' : '공개(public)로 전환할까요?',
                              content:
                                agent.owner_id == null
                                  ? 'private가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                                  : 'public이 되면 모든 사용자가 이 에이전트를 도구처럼 사용할 수 있고 A2A 공개도 켤 수 있게 됩니다.',
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
                  label: 'A2A 공개',
                  children: (
                    <ExposeSwitch
                      on={!!agent.exposed.a2a}
                      onChange={() => onToggleExpose(agent)}
                      label=""
                      onText="켬 · 다른 에이전트가 호출 가능"
                      offText="꺼짐 · 노출되지 않음"
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
          )}

          {/* ── 운영 ── */}
          {active === 'operations' && (
          <section>
            <SectionTitle>운영 — 피드백과 개선</SectionTitle>
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
                          응답 피드백(👍/👎)을 초안 평가 케이스로 — 에이전트 변경 회귀 지표
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
                          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                            👍{ops.unversionedUp} 👎{ops.unversionedDown} (버전 기록 도입 전 대화)
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
          )}
        </div>
      </div>
    </div>
  )
}

/* 값 셀 점프 래퍼(스펙 246) — bordered Descriptions 값 셀 전체를 클릭 가능하게 + 우측 화살표. */
function JumpCell({ onJump, children }: { onJump: () => void; children: React.ReactNode }) {
  return (
    <span
      onClick={onJump}
      style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', width: '100%' }}
    >
      <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{children}</span>
      <Icon name="right" size={11} style={{ color: 'var(--color-text-quaternary)', flexShrink: 0 }} />
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid var(--color-border-secondary)' }}>
      {children}
    </div>
  )
}
