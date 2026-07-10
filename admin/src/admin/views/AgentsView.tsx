/* my-agents admin — Agents view: list created agents, view detail, and
   create / edit / delete (composing building blocks). */
import { useState } from 'react'
import { Tag, Button, Avatar, Select, Input, Switch, Tooltip, Popover, Modal, message, Tabs, Checkbox } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { Icon } from '../icons'
import {
  AGENT_STATUS,
  AGENT_CONFORMANCE,
  type Agent,
  type AgentConfig,
  type VersionMeta,
} from '../mockData'
import { displayName } from '../naming'
import type { AgentFormData } from './agents/types'
import { AgentForm, typeLabel } from './agents/AgentForm'
import { AgentDetailPage } from './agents/AgentDetailPage'
import { CodeAgentDetailPage } from './agents/detail/CodeAgentDetail'
import { ExternalAgentDetailPage } from './agents/detail/ExternalAgentDetail'
import { ConnectAgentModal } from './agents/ConnectAgentModal'
import { useAgents } from './agents/useAgents'

/* ---- Main view ---- */
export default function AgentsView({ onOpenPlayground, meId }: { onOpenPlayground?: (agentRowId: string) => void; meId?: string }) {
  // 데이터 오케스트레이션(목록·레퍼런스·12 뮤테이션)은 훅으로(스펙 185 Phase B). 컴포넌트는 UI +
  // 성공 토스트·네비게이션만 소유. 뮤테이션은 A.x()가 데이터(Agent 반환/throw), 여기서 toast/nav/error.
  const A = useAgents()
  const { agents, blocks, models, collections } = A
  const [detailId, setDetailId] = useState<string | null>(null)
  const [query, setQuery] = useState('') // 리스트 검색(스펙 144 #3)
  const [sortKey, setSortKey] = useState<'name' | 'recent'>('name')
  // 출처 탭(스펙 284 — 소유/소스 Select를 탭+내것 tint가 대체).
  const [tab, setTab] = useState<'ui' | 'code' | 'external'>('ui')
  // 탭별 검색 요소(스펙 284 후속3, 사용자 지시): UI=이름+종류(Select)+A2A(Checkbox)+상태(Select),
  // Code=이름+A2A(Select)+상태(Select), External=이름만. 텍스트 검색은 이름 전용으로 정리.
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'idle' | 'offline'>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all') // UI 탭 — typeLabel 값
  const [a2aOnly, setA2aOnly] = useState(false) // UI 탭 — 체크=공개만
  const [a2aFilter, setA2aFilter] = useState<'all' | 'on' | 'off'>('all') // Code 탭
  const switchTab = (k: 'ui' | 'code' | 'external') => {
    // 탭마다 검색 요소가 달라 잔존 필터가 보이지 않게 작동하는 것을 막는다 — 전환 시 초기화.
    setTab(k)
    setQuery('')
    setTypeFilter('all')
    setA2aOnly(false)
    setA2aFilter('all')
    setStatusFilter('all')
  }
  const detail = agents.find((a) => a.id === detailId) || null
  // 풀페이지(스펙 245→246 후속) — 사용자 지적("SDK 에이전트는 드로어 그대로")으로 **전 소스** 페이지.
  // source 미기록 레거시 행은 목록과 동일하게 ui 취급.
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<{ agent: Agent; version: string | null } | null>(null)
  const [confirmDel, setConfirmDel] = useState<Agent | null>(null)
  const [exposeOff, setExposeOff] = useState<{ agent: Agent; count: number } | null>(null) // agent pending expose-off confirm
  const [connectOpen, setConnectOpen] = useState(false)

  const configOf = (a: Agent): AgentConfig => ({
    model: a.model,
    persona: a.persona,
    temperature: a.temperature ?? null,
    memories: [...(a.memories || [])],
    historyDepth: a.historyDepth,
    persistHistory: a.persistHistory ?? true,
    ephemeral: a.ephemeral ?? false,
    suggestedPrompts: a.suggestedPrompts ?? [],
    vectorTables: [...(a.vectorTables || [])],
    mcps: [...a.mcps],
    tools: [...(a.tools || [])], // 도구 단위 배선(스펙 276)
    impl: a.impl,
    capabilities: [...(a.capabilities || [])],
    toolPolicy: { ...(a.toolPolicy || {}) },
    ...(a.artifactSpec ? { artifactSpec: a.artifactSpec } : {}),
    ...(a.nodes ? { nodes: a.nodes } : {}), // 노드형 파이프라인 노드(스펙 259)
    ragMinScores: { ...(a.ragMinScores || {}) },
  })
  const draftOf = (a: Agent) => (a.versions || []).find((v) => v.status === 'draft')
  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }
  // Edit always works on a DRAFT: seed from the existing draft if present, else from active.
  const openEdit = (a: Agent) => {
    setDetailId(null)
    const d = draftOf(a)
    setEditing({ agent: a, version: d ? d.version : null })
    setFormOpen(true)
  }

  // ---- versioning + expose ----
  const nextVersion = (versions: VersionMeta[]) => {
    const max = versions.reduce(
      (n, v) => Math.max(n, parseInt(String(v.version).replace(/\D/g, ''), 10) || 0),
      0
    )
    return 'v' + (max + 1)
  }
  // 공개/비공개 전환(스펙 154) — 강등 시 서버가 A2A 자동 off.
  const setVisibility = async (agent: Agent, pub: boolean) => {
    try {
      await A.setVisibility(agent.id, pub)
      message.success(pub ? `${displayName(agent)} — 공개로 전환됨` : `${displayName(agent)} — 비공개로 전환됨`)
    } catch (e) {
      message.error(String(e))
    }
  }

  // 라이브 세션 카운트는 더 이상 추적하지 않는다(ADMIN_SESSIONS 제거). UX용 모달만 유지.
  const toggleExpose = async (agent: Agent) => {
    // 외부에서 받아온 에이전트만 재공개 금지(스펙 152) — code(제1자 SDK)는 1홉 중계 노출(스펙 154).
    if (!agent.exposed.a2a && agent.source === 'external') {
      message.warning('외부에서 가져온 에이전트는 A2A로 재공개할 수 없습니다')
      return
    }
    if (!agent.exposed.a2a) {
      try {
        await A.expose(agent.id, true)
        message.success(`${agent.name} — A2A 공개됨`)
      } catch (e) {
        message.error(String(e))
      }
      return
    }
    // turning OFF — 확인 모달을 띄운다(액션은 모두 exposeAgent(false)).
    setExposeOff({ agent, count: 0 })
  }
  const exposeOffApply = async (mode: 'drain' | 'revoke') => {
    if (!exposeOff) return
    const { agent } = exposeOff
    try {
      await A.expose(agent.id, false)
      message.success(mode === 'drain' ? `${agent.name} 사용 중단 — A2A 비공개로 전환` : `${agent.name} — A2A 철회됨`)
    } catch (e) {
      message.error(String(e))
    }
    setExposeOff(null)
  }
  const deprecate = () => exposeOffApply('drain')
  const revokeNow = () => exposeOffApply('revoke')
  const activateVersion = async (agent: Agent, v: VersionMeta) => {
    try {
      await A.activate(agent.id, v.version)
      message.success(`${agent.name} ${v.version} 활성화됨 — 서빙 시작`)
    } catch (e) {
      message.error(String(e))
    }
  }
  const newDraft = async (agent: Agent) => {
    try {
      await A.fork(agent.id)
      message.success(`${agent.name} 새 초안 생성됨`)
    } catch {
      // 400: 이미 초안이 있음 등 — 서버 가드.
      message.warning('새 초안을 만들 수 없습니다 — 이미 초안이 있는지 확인하세요')
    }
  }
  // 테스트 = 플레이그라운드로 실제 이동(스펙 144 #2 — 토스트만 띄우던 것은 액션 오인 유발).
  const testVersion = (agent: Agent, _v: VersionMeta) => {
    setDetailId(null)
    onOpenPlayground?.(agent.id)
  }
  const revertToDraft = async (agent: Agent, v: VersionMeta) => {
    try {
      await A.revert(agent.id, v.version)
      message.success(`${v.version} 초안으로 되돌림${v.status === 'active' ? ' — 이전 버전으로 롤백' : ''}`)
    } catch {
      // 서버가 가드를 강제(400 + 한국어 detail). api.ts 에러는 status만 담으므로 일반 메시지로 안내.
      message.warning('되돌릴 수 없습니다 — 조건을 확인하세요')
    }
  }

  const save = async (data: AgentFormData) => {
    const config: AgentConfig = {
      model: data.model,
      persona: data.persona,
      temperature: data.temperature,
      memories: data.memories,
      historyDepth: data.historyDepth,
      persistHistory: data.persistHistory,
      ephemeral: data.ephemeral,
      suggestedPrompts: data.suggestedPrompts,
      vectorTables: data.vectorTables,
      mcps: data.mcps,
      tools: data.tools, // 도구 단위 배선(스펙 276) — mcps는 폼이 서버 합집합으로 파생
      // 빈 impl은 config에서 생략(기본 UI 에이전트 동작 보존 — undefined면 백엔드가 default 경로).
      ...(data.impl ? { impl: data.impl } : {}),
      capabilities: data.capabilities,
      toolPolicy: data.toolPolicy, // 도구 승인 오버라이드(스펙 177 P2) — 백엔드 완화 게이트가 admin 강제
      // 노코드 산출물형(스펙 190) — impl=artifact_form일 때만 명세 저장. 아니면 생략(무관 에이전트 오염 방지).
      ...(data.impl === 'artifact_form' && data.artifactSpec ? { artifactSpec: data.artifactSpec } : {}),
      // 노드형(스펙 259) — impl=pipeline일 때만 노드 저장. mcps/vectorTables는 폼이 노드 도구 합집합에서
      // 파생해 data에 이미 담아 보냄(finalizeForm) — 위 mcps/vectorTables 라인이 그 값을 저장.
      ...(data.impl === 'pipeline' && data.nodes?.length ? { nodes: data.nodes } : {}),
      // 컬렉션별 문서 검색 최소 유사도(스펙 191 v2) — 배선된 컬렉션 중 값>0인 것만 저장(무관/0 제거).
      // 조율형은 capabilities의 `rag:*`가 배선 표면(스펙 239 codex #4 — vectorTables만 돌면 조율형
      // 슬라이더 값이 조용히 유실되던 버그).
      ...(() => {
        const wired = new Set<string>(data.vectorTables)
        data.capabilities.forEach((c) => {
          if (c.startsWith('rag:')) wired.add(c.slice(4))
        })
        const m: Record<string, number> = {}
        for (const c of wired) {
          const v = data.ragMinScores?.[c]
          if (typeof v === 'number' && v > 0) m[c] = v
        }
        return Object.keys(m).length ? { ragMinScores: m } : {}
      })(),
    }
    try {
      if (editing) {
        // description은 항상 현재 폼 값을 전송('' = 비우기, 스펙 210)
        await A.update(editing.agent.id, data.name, config, data.description)
        message.success(`초안에 저장됨 — 활성화하면 게시됩니다`)
        // 편집을 마치면 그 에이전트의 드로워로 복귀(스펙 144 #1 — 이어서 "활성화"를 누르는 동선).
        setDetailId(editing.agent.id)
      } else {
        await A.create(data.name, config, data.description || null)
        message.success(`"${data.name}" 생성됨 — v1 초안, 테스트 후 활성화`)
      }
      setFormOpen(false)
      setEditing(null)
    } catch (e) {
      message.error(String(e))
    }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    const target = confirmDel
    try {
      await A.remove(target.id)
      message.success(`"${target.name}" ${target.source !== 'ui' ? '등록 해제됨' : '삭제됨'}`)
      setConfirmDel(null)
      setDetailId(null)
    } catch (e) {
      message.error(String(e))
    }
  }

  // 복제(스펙 120) — 기존 설정을 새 ui 초안으로 복사(저마찰 재사용). 관리 권한 불요(가시하면 복제 가능).
  const onClone = async (a: Agent) => {
    try {
      const created = await A.clone(a.id)
      message.success(`"${a.name}" 복제됨 → "${created.name}"`)
      setDetailId(null)
    } catch (e) {
      message.error(String(e))
    }
  }

  // ---- 원격 에이전트 연결(스펙 057): URL 하나로 백엔드가 카드 fetch·검증·provenance 자동분류 ----
  // 프론트는 매니페스트를 날조하지 않는다 — 토큰 마스킹·분류는 모두 서버. 반환 source로 토스트를 도출.
  const connectAgent = async (data: { url: string; token: string }) => {
    try {
      const created = await A.connect(data.url, data.token || undefined)
      const kind = created.source === 'code' ? 'SDK 에이전트 (코드)' : '외부 A2A'
      message.success(`"${created.name || '원격 에이전트'}" 연결됨 — ${kind}, 읽기 전용`)
      setConnectOpen(false)
    } catch (e) {
      message.error(`연결 실패 — ${String(e)}`)
    }
  }
  const resync = async (agent: Agent) => {
    try {
      await A.resync(agent.id)
      message.success(`${agent.name} 재동기화됨 — 최신 배포(commit) 반영`)
    } catch (e) {
      message.error(String(e))
    }
  }
  // 페르소나 스냅샷을 현재 원본으로 갱신(스펙 161) — 저장 시점 복사본이 오래됐을 때 명시적 반영.
  const refreshPersona = async (agent: Agent) => {
    try {
      await A.refreshPersona(agent.id)
      message.success(`${agent.name} 페르소나 갱신됨`)
    } catch (e) {
      message.error(String(e))
    }
  }

  const q = query.trim().toLowerCase()
  // '타인' 판정은 meId 비교(admin은 can_manage가 늘 true — e2e 147 실측 결함 교정)
  const ownerKind = (a: Agent) =>
    a.owner_id == null ? 'shared' : meId !== undefined ? (a.owner_id === meId ? 'mine' : 'others') : a.can_manage === false ? 'others' : 'mine'
  const visibleAgents = agents
    // 텍스트 검색=이름 전용(스펙 284 후속3 — 종류·A2A·상태는 명시 컨트롤로 이동).
    .filter((a) => !q || a.name.toLowerCase().includes(q))
    // 타인 private는 기본 숨김(스펙 147 — 소유자에게만 보임). opt-in 해제는 285(가시성 재설계)로 이관.
    .filter((a) => ownerKind(a) !== 'others')
    // 출처 탭(스펙 284) — 소스 필터 Select 대체.
    .filter((a) => (a.source || 'ui') === tab)
    // 탭별 필터(스펙 284 후속3)
    .filter((a) => tab !== 'ui' || typeFilter === 'all' || typeLabel(a.impl) === typeFilter)
    .filter((a) => tab !== 'ui' || !a2aOnly || !!a.exposed.a2a)
    .filter((a) => tab !== 'code' || a2aFilter === 'all' || (a2aFilter === 'on') === !!a.exposed.a2a)
    .filter((a) => tab === 'external' || statusFilter === 'all' || a.status === statusFilter)
    .slice()
    .sort((x, y) =>
      sortKey === 'name' ? x.name.localeCompare(y.name, 'ko') : 0 /* recent=서버 응답 순서(최신 생성이 앞) 보존 */
    )

  // 보조 줄 구성 요소(스펙 146 — 2줄 행): 준수·MCP·RAG만(소유·출처는 284에서 tint·탭으로).
  const renderConformance = (a: Agent) => {
    // 비준수(non_conforming)는 code/external의 **정상 상태**(원격=다른 종류)라 전 행 표시=정보 0
    // (사용자 지적, 284 후속2) — 진짜 문제(설정 실패)만 예외 표시.
    if ((a.conformance || 'conforming') !== 'config_error') return null
    const c = AGENT_CONFORMANCE[a.conformance || 'conforming'] || AGENT_CONFORMANCE.conforming
    const isError = a.conformance === 'config_error'
    return (
      <Tooltip title={c.desc}>
        <Tag color={c.tag === 'default' ? undefined : c.tag}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: isError ? 600 : 400 }}>
            {c.icon ? <Icon name={c.icon} size={11} /> : null}
            {c.label}
          </span>
        </Tag>
      </Tooltip>
    )
  }
  const agentSubRow = (a: Agent) => {
    const rags = [
      ...(a.vectorTables || []),
      ...(a.capabilities || []).filter((c) => c.startsWith('rag:')).map((c) => c.slice(4)),
    ]
    return (
      <>
        {/* 소유·출처 태그는 소멸(스펙 284) — 출처=탭, 내 것=행 tint가 대체. 예외(준수)만 표시. */}
        {renderConformance(a)}
        {a.mcps.map((m) => (
          <Tag key={`m-${m}`} color="cyan">{m}</Tag>
        ))}
        {[...new Set(rags)].map((r) => (
          <Tag key={`r-${r}`} color="geekblue">rag:{r}</Tag>
        ))}
      </>
    )
  }

  const columns: Column<Agent>[] = [
    {
      key: 'name',
      title: '에이전트',
      width: '26%', // 내용 최다(아바타+이름+모델) — MCP 컬럼 제거분 흡수(스펙 145 후속3)
      render: (a) => {
        const isCode = a.source === 'code'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Avatar
              size="small"
              style={{
                background: isCode ? 'var(--geekblue-1)' : 'var(--gray-12)',
                color: isCode ? 'var(--geekblue-7)' : '#fff',
                flex: 'none', // fixed 레이아웃 좁은 셀에서 원형 유지(찌그러짐 방지 — 사용자 보고)
              }}
            >
              <Icon name={isCode ? 'code' : 'robot'} size={14} />
            </Avatar>
            <div>
              <Tooltip title={a.description || undefined}>
                <div style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{displayName(a)}</div>
              </Tooltip>
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
                {a.model}
              </div>
            </div>
          </div>
        )
      },
    },
    // 페르소나 컬럼 제거(스펙 284 ④). UI 탭엔 에이전트 종류(283 typeLabel 단일 출처, 284 ③).
    ...(tab === 'ui'
      ? [{
          key: 'type',
          title: '종류',
          width: 110,
          render: (a: Agent) => <Tag style={{ margin: 0 }}>{typeLabel(a.impl)}</Tag>,
        } satisfies Column<Agent>]
      : []),
    {
      key: 'version',
      width: 96, // 짧고 고정적인 내용 — 비율 대신 고정폭(v6+초안이 세로로 깨지던 것)
      title: '버전',
      render: (a) => {
        if (a.source === 'code')
          return (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.commit || a.activeVersion}
            </code>
          )
        if (a.source === 'external')
          return (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.card?.version ? 'v' + a.card.version : '—'}
            </code>
          )
        const draft = (a.versions || []).find((v) => v.status === 'draft')
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.activeVersion}
            </code>
            {draft ? <Tag color="gold" style={{ whiteSpace: 'nowrap', margin: 0 }}>+초안</Tag> : null}
          </span>
        )
      },
    },
    {
      key: 'exposed',
      width: '10%',
      title: 'A2A', // 프로토콜을 켬=공개 — 라벨 간결화(사용자 피드백)
      render: (a) =>
        // external만 재공개 금지(스펙 152) — ui는 직접 서빙, code는 1홉 중계(스펙 154). 목록에서도
        // code 공개 상태가 보여야 운영자가 놓치지 않는다(codex 154 Low).
        a.source === 'external' ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>—</span>
        ) : (
          <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Tooltip title={a.owner_id != null ? 'private 에이전트는 A2A를 켤 수 없습니다(소유자 전용)' : undefined}>
              <Switch size="small" checked={!!a.exposed.a2a} disabled={a.owner_id != null} onChange={() => toggleExpose(a)} />
            </Tooltip>
            <span style={{ fontSize: 12, color: a.exposed.a2a ? 'var(--color-success)' : 'var(--color-text-tertiary)' }}>
              {a.exposed.a2a ? '켬' : '꺼짐'}
            </span>
          </span>
        ),
    },
    // 상태 컬럼은 External 제외(스펙 284 후속3, 사용자: 외부는 우리가 상태 관리하지 않음).
    ...(tab === 'external' ? [] : [{
      key: 'status',
      width: 64,
      title: '상태',
      align: 'center' as const,
      render: (a) => {
        // 신호등(스펙 284 ⑥) — 고정 슬롯의 색 점 + 툴팁. 색·라벨·의미=AGENT_STATUS 단일 출처(스펙 286).
        const st = AGENT_STATUS[a.status] ?? AGENT_STATUS.offline
        return (
          <Tooltip title={st.desc}>
            <span aria-label={st.label} style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: st.color }} />
          </Tooltip>
        )
      },
    } satisfies Column<Agent>]),
    {
      key: 'actions',
      width: 80,
      title: '',
      align: 'right',
      render: (a) => (
        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', gap: 2 }}>
          {a.can_manage === false ? (
            // 비소유(스펙 114) — 관리 잠금, 삭제 버튼도 숨김.
            <Button type="text" size="small" icon={<Icon name="lock" />} disabled title="다른 사용자 소유 — 관리 권한 없음" />
          ) : a.source === 'code' || a.source === 'external' ? (
            <Button
              type="text"
              size="small"
              icon={<Icon name="lock" />}
              disabled
              title={a.source === 'external' ? '외부 A2A 카드로 관리됨 — 편집 잠금' : '코드에서 관리됨 — 편집 잠금'}
            />
          ) : (
            <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => openEdit(a)} />
          )}
          {a.can_manage !== false && (
            <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(a)} />
          )}
        </span>
      ),
    },
  ]

  return (
    <Page
      title="에이전트"
      subtitle={`빌딩 블록으로 구성하거나 코드로 배포한 에이전트 ${agents.length}개`}
      actions={
        detail ? undefined : (
          <span style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <Button icon={<Icon name="link" />} onClick={() => setConnectOpen(true)}>
              원격 에이전트 연결
            </Button>
            <Button type="primary" icon={<Icon name="plus" />} onClick={openCreate}>
              새 에이전트
            </Button>
          </span>
        )
      }
    >
      {detail && detail.source === 'code' ? (
        <CodeAgentDetailPage
          agent={detail}
          onBack={() => setDetailId(null)}
          onDelete={setConfirmDel}
          onClone={onClone}
          onResync={resync}
          onToggleExpose={toggleExpose}
          onSetVisibility={setVisibility}
          onRefreshPersona={refreshPersona}
        />
      ) : detail && detail.source === 'external' ? (
        <ExternalAgentDetailPage
          agent={detail}
          onBack={() => setDetailId(null)}
          onDelete={setConfirmDel}
          onClone={onClone}
        />
      ) : detail ? (
        /* 에이전트 상세 풀페이지(스펙 245) — 목록을 대체 렌더(뒤로가기로 복귀). ui + 레거시(source 미기록). */
        <AgentDetailPage
          agent={detail}
          agents={agents}
          onBack={() => setDetailId(null)}
          onEdit={openEdit}
          onDelete={setConfirmDel}
          onClone={onClone}
          onToggleExpose={toggleExpose}
          onSetVisibility={setVisibility}
          onActivate={activateVersion}
          onTest={testVersion}
          onRevert={revertToDraft}
          onNewDraft={newDraft}
          onRefreshPersona={refreshPersona}
        />
      ) : (
      <>
      {/* 출처 탭(스펙 284 ②) — 데이터 집합 전환=Tabs(212 규칙). 소유/소스 Select 대체. */}
      <Tabs
        activeKey={tab}
        onChange={(k) => switchTab(k as 'ui' | 'code' | 'external')}
        items={[
          { key: 'ui', label: 'Internal (UI)' },
          { key: 'code', label: 'Internal (Code)' },
          { key: 'external', label: 'External' },
        ]}
      />
      {/* 탭 안 검색(스펙 284 ⑤) — 탭별로 꼭 필요한 조건만(placeholder가 축을 안내). */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Input
          allowClear
          prefix={<Icon name="search" size={13} />}
          placeholder="이름 검색"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ maxWidth: 220 }}
        />
        {tab === 'ui' && (
          <Select
            value={typeFilter}
            onChange={setTypeFilter}
            style={{ width: 130 }}
            popupMatchSelectWidth={false}
            options={[
              { value: 'all', label: '종류: 전체' },
              { value: '직접 응답', label: '직접 응답' },
              { value: '조율형', label: '조율형' },
              { value: '산출물형', label: '산출물형' },
              { value: '노드형', label: '노드형' },
            ]}
          />
        )}
        {tab === 'ui' && (
          <Checkbox checked={a2aOnly} onChange={(e) => setA2aOnly(e.target.checked)}>
            A2A 공개만
          </Checkbox>
        )}
        {tab === 'code' && (
          <Select
            value={a2aFilter}
            onChange={setA2aFilter}
            style={{ width: 120 }}
            popupMatchSelectWidth={false}
            options={[
              { value: 'all', label: 'A2A: 전체' },
              { value: 'on', label: 'A2A 켬' },
              { value: 'off', label: 'A2A 꺼짐' },
            ]}
          />
        )}
        {tab !== 'external' && (
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            style={{ width: 130 }}
            popupMatchSelectWidth={false}
            options={[
              { value: 'all', label: '상태: 전체' },
              { value: 'online', label: '온라인' },
              { value: 'idle', label: '유휴' },
              { value: 'offline', label: '오프라인' },
            ]}
          />
        )}
        <Select
          value={sortKey}
          onChange={setSortKey}
          style={{ width: 130 }}
          popupMatchSelectWidth={false}
          options={[
            { value: 'name', label: '이름순' },
            { value: 'recent', label: '최근 등록순' },
          ]}
        />
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {visibleAgents.length}/{agents.length}개
        </span>
        <Popover
          title="표시 안내"
          content={
            <div style={{ fontSize: 13, maxWidth: 380 }}>
              {/* 범례(스펙 284) — 출처=탭, 내 것=행 배경, 상태=신호등, 태그는 예외·연결만. */}
              <div style={{ display: 'grid', gridTemplateColumns: '128px 1fr', columnGap: 12, rowGap: 12, alignItems: 'start' }}>
                <span style={{ display: 'inline-flex', gap: 6 }}>
                  <span style={{ background: 'rgba(22,119,255,0.12)', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}>연한 파랑</span>
                  <span style={{ background: 'rgba(82,196,26,0.14)', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}>연한 초록</span>
                </span>
                <span style={{ color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                  내가 만든 에이전트 — 파랑=비공개(나만 사용), 초록=공개
                </span>

                <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--blue-6)', display: 'inline-block' }} />
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--gold-6)', display: 'inline-block' }} />
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--red-6)', display: 'inline-block' }} />
                </span>
                <span style={{ color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                  상태 — 파랑=온라인(서빙 중) · 노랑=유휴(초안만) · 빨강=오프라인(연결 안 됨)
                </span>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  <Tag color="red">설정 오류</Tag>
                </div>
                <span style={{ color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>문제가 있을 때만 표시</span>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  <Tag color="cyan">MCP 이름</Tag><Tag color="geekblue">rag:컬렉션</Tag>
                </div>
                <span style={{ color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>연결된 도구·문서</span>
              </div>
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--color-border-secondary)', color: 'var(--color-text-tertiary)', lineHeight: 1.5 }}>
                출처는 상단 탭으로 구분 · A2A 스위치=다른 에이전트의 호출 허용(공개만 켤 수 있음)
              </div>
            </div>
          }
        >
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', cursor: 'help', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            <Icon name="info-circle" size={13} /> 표시 안내
          </span>
        </Popover>
      </div>
      <DataTable
        columns={columns}
        rows={visibleAgents}
        onRowClick={(a) => setDetailId(a.id)}
        subRow={agentSubRow}
        // 내 것 tint(스펙 284 ①, 후속2) — private=연한 파랑(레드는 거부감, 사용자 지시),
        // 공개된 내 것=연한 그린(285 생성자 축 이후 등장).
        rowTint={(a) =>
          a.owner_id != null && meId !== undefined && a.owner_id === meId
            ? 'blue' // 내 것 + private(owner_id 있음 = 비공개, 147 의미론)
            : undefined
        }
      />
      </>
      )}

      <ConnectAgentModal open={connectOpen} onCancel={() => setConnectOpen(false)} onConnect={connectAgent} />
      <AgentForm
        open={formOpen}
        mode={editing ? 'edit' : 'create'}
        blocks={blocks}
        models={models}
        collections={collections}
        agents={agents}
        draftVersion={
          editing
            ? draftOf(editing.agent)
              ? draftOf(editing.agent)!.version
              : nextVersion(editing.agent.versions)
            : null
        }
        initial={
          editing
            ? (() => {
                const a = editing.agent
                const d = draftOf(a)
                const c: AgentConfig = d ? d.config || configOf(a) : configOf(a)
                return {
                  name: a.name,
                  description: a.description ?? '',
                  model: c.model || a.model,
                  persona: c.persona || a.persona,
                  temperature: c.temperature ?? a.temperature ?? null,
                  memories: [...(c.memories || [])],
                  historyDepth: c.historyDepth != null ? c.historyDepth : a.historyDepth,
                  persistHistory: c.persistHistory ?? a.persistHistory ?? true,
                  ephemeral: c.ephemeral ?? a.ephemeral ?? false,
                  suggestedPrompts: c.suggestedPrompts ?? a.suggestedPrompts ?? [],
                  vectorTables: [...(c.vectorTables || [])],
                  mcps: [...(c.mcps || [])],
                  tools: [...(c.tools || [])], // 도구 단위 배선(스펙 276) — 구저장 빈값은 폼이 하이드레이션
                  impl: c.impl ?? a.impl ?? '',
                  capabilities: [...(c.capabilities || a.capabilities || [])],
                  toolPolicy: { ...(c.toolPolicy || a.toolPolicy || {}) }, // 승인 오버라이드(스펙 177 P2)
                  ...(c.artifactSpec || a.artifactSpec
                    ? { artifactSpec: c.artifactSpec || a.artifactSpec } // 노코드 산출물형 명세(스펙 190) 재로드
                    : {}),
                  ...(c.nodes || a.nodes
                    ? { nodes: c.nodes || a.nodes } // 노드형 파이프라인 노드(스펙 259) 재로드
                    : {}),
                  ragMinScores: { ...(c.ragMinScores || a.ragMinScores || {}) }, // 컬렉션별 최소 유사도(스펙 191 v2) 재로드
                }
              })()
            : null
        }
        onCancel={() => {
          setFormOpen(false)
          // 편집 취소도 출발점(그 에이전트 드로워)으로 복귀(스펙 144 #1). 신규 생성 취소는 리스트.
          if (editing) setDetailId(editing.agent.id)
          setEditing(null)
        }}
        onSave={save}
      />

      <Modal
        open={!!confirmDel}
        title={confirmDel && confirmDel.source !== 'ui' ? '에이전트 등록을 해제할까요?' : '에이전트를 삭제할까요?'}
        okText={confirmDel && confirmDel.source !== 'ui' ? '등록 해제' : '삭제'}
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          confirmDel.source === 'code' ? (
            <div>
              <b>{confirmDel.name}</b>를 콘솔에서 등록 해제합니다. 배포된 코드는 그대로 실행되지만, 이 콘솔에서의
              연결·모니터링과 A2A 공개가 제거됩니다.
            </div>
          ) : confirmDel.source === 'external' ? (
            <div>
              <b>{confirmDel.name}</b>를 콘솔에서 등록 해제합니다. 외부 A2A 서비스는 그대로지만, 이 콘솔에서의
              카드 등록·모니터링과 A2A 공개가 제거됩니다.
            </div>
          ) : (
            <div>
              <b>{confirmDel.name}</b> 및 공개 엔드포인트가 영구 삭제됩니다. 진행 중인 세션도 종료됩니다. 되돌릴 수
              없습니다.
            </div>
          )
        ) : null}
      </Modal>

      <Modal
        open={!!exposeOff}
        title="A2A 공개를 끌까요?"
        width={460}
        onCancel={() => setExposeOff(null)}
        footer={
          exposeOff ? (
            <>
              <Button onClick={() => setExposeOff(null)}>취소</Button>
              <Button icon={<Icon name="pause-circle" />} onClick={deprecate}>
                사용 중단(드레인)
              </Button>
              <Button danger type="primary" icon={<Icon name="close" />} onClick={revokeNow}>
                즉시 철회
              </Button>
            </>
          ) : null
        }
      >
        {exposeOff ? (
          <div>
            <div style={{ marginBottom: 12 }}>
              <b>{exposeOff.agent.name}</b>의 A2A 공개를 끕니다. 오프라인 방식을 선택하세요:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="pause-circle" size={15} style={{ color: 'var(--volcano-6)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>사용 중단(드레인)</b> — 신규 세션을 막고 진행 중인 세션을 끝낸 뒤 비공개로 전환. 소비자에게 가장
                  안전.
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="close-circle" size={15} style={{ color: 'var(--color-error)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>즉시 철회</b> — 엔드포인트를 즉시 차단; 진행 중인 세션이 종료되고 외부 호출자는 오류를 받습니다.
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </Page>
  )
}
