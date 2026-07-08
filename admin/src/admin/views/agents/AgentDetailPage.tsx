/* 에이전트 상세 풀페이지(스펙 245) — 640px 드로어에 12블록이 쌓이던 것을 관심사별 5섹션
   (개요/구성/버전·배포/공개·연동/운영) + 좌측 섹션 네비로 재배치. 로컬(ui) 에이전트 전용
   (code/external은 블록 수가 적어 기존 드로어 유지 — 승격은 후속). 기능은 드로어와 동일(이동만). */
import { useEffect, useRef, useState } from 'react'
import { Tag, Button, Avatar, Alert, Modal, Descriptions, Grid } from 'antd'
import { VersionHistory, ExposeSwitch } from '../../shared'
import { Icon } from '../../icons'
import { AgentMemoryPanel } from '../AgentMemoryPanel'
import type { Agent, VersionMeta } from '../../mockData'
import { displayName } from '../../naming'
import { PersonaStaleNote } from './PersonaStaleNote'
import { FeedbackHarvestButton } from './FeedbackHarvestButton'
import { IdRow } from './primitives'
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

  const jump = (key: string) => {
    setActive(key)
    bodyRef.current?.querySelector(`[data-section="${key}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const draft = (agent.versions || []).find((v) => v.status === 'draft')
  const canManage = agent.can_manage !== false

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
    <div>
      {/* 상단 바 — 뒤로가기 + 정체성 + 주요 행동(개요 섹션과 별개로 항상 보임) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Button icon={<Icon name="arrow-left" />} onClick={onBack}>
          목록
        </Button>
        <Avatar size="large" style={{ background: 'var(--gray-12)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{displayName(agent)}</div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
        {agent.conformance === 'config_error' ? (
          <Tag color="red">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
              <Icon name="exclamation-circle" size={11} /> 설정 실패
            </span>
          </Tag>
        ) : (
          <Tag color="green">
            서빙 중 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.activeVersion}</code>
          </Tag>
        )}
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
        <div ref={bodyRef} style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 860 }}>
          {/* ── 개요 ── */}
          <section data-section="overview">
            <SectionTitle>개요</SectionTitle>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>활성 구성(현재 서빙 중)</span>
              <div style={{ flex: 1 }} />
              {(agent.environments || []).map((env) =>
                env === 'production' ? <Tag key={env} color="geekblue">{env}</Tag> : <Tag key={env}>{env}</Tag>
              )}
            </div>
            <Descriptions
              column={1}
              size="small"
              layout={isMobile ? 'vertical' : 'horizontal'}
              items={[
                { key: 'model', label: '모델', children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span> },
                { key: 'persona', label: '페르소나', children: agent.persona },
                { key: 'sessions', label: '세션', children: <>활성 {agent.sessions}개</> },
              ]}
            />
            <PersonaStaleNote agent={agent} onRefresh={onRefreshPersona} />
          </section>

          {/* ── 구성 ── */}
          <section data-section="config">
            <SectionTitle>구성 — 무엇을 쓸 수 있나</SectionTitle>
            <Descriptions
              column={1}
              size="small"
              layout={isMobile ? 'vertical' : 'horizontal'}
              items={[
                {
                  key: 'memories',
                  label: '메모리',
                  children: (agent.memories || []).length ? (
                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                      {agent.memories.map((m) => <Tag key={m} color="purple">{m}</Tag>)}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--color-text-tertiary)' }}>메모리 없음</span>
                  ),
                },
                {
                  key: 'history',
                  label: '채팅 히스토리',
                  children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
                },
                ...((agent.memories || []).includes('장기 기억 (mem0)')
                  ? [{
                      key: 'vectors',
                      label: '벡터 테이블',
                      children: (agent.vectorTables || []).length ? (
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                          {agent.vectorTables.map((t) => (
                            <Tag key={t} color="cyan"><code style={{ fontFamily: 'var(--font-family-code)' }}>{t}</code></Tag>
                          ))}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--color-text-tertiary)' }}>연결 안 함 (외부 지식 없음)</span>
                      ),
                    }]
                  : []),
                {
                  key: 'mcps',
                  label: 'MCP',
                  children: (agent.mcps || []).length ? (
                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                      {agent.mcps.map((m) => <Tag key={m} color="cyan">{m}</Tag>)}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--color-text-tertiary)' }}>없음</span>
                  ),
                },
              ]}
            />
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

          {/* ── 버전·배포 ── */}
          <section data-section="versions">
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

          {/* ── 공개·연동 ── */}
          <section data-section="sharing">
            <SectionTitle>공개·연동 — 누가 쓸 수 있나</SectionTitle>
            {canManage ? (
              <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)', background: 'var(--gray-2)', marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>공개 범위</div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    {agent.owner_id == null
                      ? 'public · 모두 도구처럼 사용 가능(A2A 켜기 가능)'
                      : 'private · 소유자만 사용(A2A 불가)'}
                  </div>
                </div>
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
              </div>
            ) : null}
            <ExposeSwitch
              on={!!agent.exposed.a2a}
              onChange={() => onToggleExpose(agent)}
              label="A2A로 공개"
              onText="켬 · 다른 에이전트가 호출 가능"
              offText="꺼짐 · 노출되지 않음"
            />
            {agent.exposed.a2a ? (
              <div style={{ marginTop: 10, padding: 14, border: '1px solid var(--green-3)', background: 'var(--green-1)', borderRadius: 'var(--radius-lg)' }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icon name="global" size={12} style={{ color: 'var(--green-7)' }} />
                  A2A 식별자(소비자와 공유)
                </div>
                <IdRow label="Agent ID" value={agent.agentId} />
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 8px 84px' }}>
                  불변 · 모든 환경에서 동일한 ID
                </div>
                <IdRow label="A2A 카드" value={a2aCardUrl(agent.id)} />
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 0 84px' }}>
                  이 URL을 <strong>“원격 에이전트 연결”</strong>에 그대로 붙여 등록·테스트하세요. 루프백/사설
                  주소면 백엔드에 <code style={{ fontFamily: 'var(--font-family-code)' }}>A2A_ALLOWED_HOSTS=127.0.0.1</code>가 필요합니다.
                </div>
              </div>
            ) : null}
          </section>

          {/* ── 운영 ── */}
          <section data-section="operations">
            <SectionTitle>운영 — 피드백과 개선</SectionTitle>
            {canManage ? (
              <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>피드백 수확</div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    응답 피드백(👍/👎)을 초안 평가 케이스로 — 에이전트 변경 회귀 지표
                  </div>
                </div>
                <FeedbackHarvestButton agentId={agent.id} />
              </div>
            ) : (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>운영 도구는 관리 권한이 필요합니다.</span>
            )}
            {ops && (ops.unversionedUp > 0 || ops.unversionedDown > 0) && (
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
                버전 미기록 피드백 👍{ops.unversionedUp} 👎{ops.unversionedDown} (버전 기록 도입 전 대화)
              </div>
            )}
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
              버전별 성적·피드백은 위 <a onClick={() => jump('versions')}>버전·배포</a>의 이력 행에 표시됩니다.
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid var(--color-border-secondary)' }}>
      {children}
    </div>
  )
}
