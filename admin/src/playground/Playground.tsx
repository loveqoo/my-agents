/* my-agents debug console — app shell. Loads real agents, drives the real
   streaming chat API, and links each assistant turn → the Inspector from the
   real execution trace. 3-pane: agent picker (in header) + debug chat + Inspector. */
import { useEffect, useRef, useState } from 'react'
import { message, Grid, Drawer, Splitter, Button, Modal, Select, Input } from 'antd'
import { DebugChat } from './DebugChat'
import { Inspector } from './Inspector'
import { OverridePanel, overrideDefaults, overridePayload, type Overrides } from './OverridePanel'
import { Icon } from '../admin/icons'
import type { ChatMsg, Trace } from './agentData'
import type { Agent, BlockCategory, Session } from '../admin/mockData'
import {
  listAgents, streamChat, streamChatA2A, uploadChatAttachment, getBlocks, listModels, listSessions, getSessionMessages, listCollections,
  createCollection, uploadDocument, listDocuments,
  getApproval, resolveApproval,
  type ChatMessage, type Model, type Collection, type ChatFormFrame, type MessageFeedback, type ChatAttachmentDraft,
} from '../api'
import { onAgentsChanged } from '../agentsBus'
import { isA2AExposed } from './DebugChat'

export function Playground({
  initialAgentId = null,
  onConsumedInitial,
  meIsSuperuser = false,
}: {
  initialAgentId?: string | null
  onConsumedInitial?: () => void
  meIsSuperuser?: boolean // 인라인 승인(스펙 180) — admin 승인 대기를 그 자리서 처리 가능한지 판정
} = {}) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [activeId, setActiveId] = useState('')
  const [convos, setConvos] = useState<Record<string, ChatMsg[]>>({})
  const [sessions, setSessions] = useState<Record<string, string>>({})
  // 세션 이어가기(스펙 055): 활성 에이전트의 과거 세션 목록 + 로딩 상태.
  const [sessionList, setSessionList] = useState<Session[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  // 버전 미리보기(스펙 243) — 에이전트별 지정 버전(undefined=활성). 변경=새 대화(혼재 방지).
  const [pinnedVersions, setPinnedVersions] = useState<Record<string, string | undefined>>({})
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  // mem0 user_id 축은 서버가 로그인 유저에서 도출한다(스펙 032) — Playground에 수동 입력 없음.
  // 오버라이드 패널(스펙 025) — 카탈로그(모델·블록) + 에이전트별 적용 오버라이드.
  const [models, setModels] = useState<Model[]>([])
  const [blocks, setBlocks] = useState<Record<string, BlockCategory>>({})
  const [collections, setCollections] = useState<Collection[]>([]) // 조율형 위임 카탈로그(문서, 스펙 122)
  const [overridePanelOpen, setOverridePanelOpen] = useState(false)
  const [appliedByAgent, setAppliedByAgent] = useState<Record<string, Overrides>>({})
  // 첨부→지식 저장(스펙 405) 상태 — 세션 연결·인제스트 잡·대상 선택 모달.
  interface KJob { id: string; filename: string; collection: string; status: 'ingesting' | 'ready' | 'error'; err?: string }
  const [wiredByAgent, setWiredByAgent] = useState<Record<string, string[]>>({})
  const [kJobsByAgent, setKJobsByAgent] = useState<Record<string, KJob[]>>({})
  const [kModal, setKModal] = useState<{ file: File } | null>(null)
  const [kTarget, setKTarget] = useState<string>('') // 기존 컬렉션 id 또는 ''(새로 만들기)
  const [kNewName, setKNewName] = useState<string>('')
  // A2A 루프백 테스트 모드(스펙 155) — 에이전트별. true면 send가 /agents/{id}/a2a(JSON-RPC)로
  // 외부 소비자처럼 호출. 노출 에이전트에서만 토글 노출. 기본 false(직접 /chat — 무회귀).
  const [a2aByAgent, setA2aByAgent] = useState<Record<string, boolean>>({})
  const controllerRef = useRef<AbortController | null>(null)
  // 세션 로드 레이스 가드(스펙 055): 늦게 도착한 응답이 최신 선택을 덮어쓰지 않게 하는 시퀀스.
  const sessionLoadSeqRef = useRef(0)
  // 승인 대기 폴링(스펙 179): 위험 도구가 그래프를 멈추면 승인 프레임이 온다. 백엔드는 승인 시
  // 서버사이드로 재개해 결과를 세션에 영속하나 대기 중 채팅엔 라이브 push가 없다(§7 빚). 요청자
  // UI가 승인 상태를 폴링해, 해소되면 세션 메시지를 다시 불러 완료 턴을 표시한다.
  const [pendingApproval, setPendingApproval] = useState<{ id: string; convoId: string; approver?: string } | null>(null)
  // 산출물형 폼 대기(스펙 188) — form 프레임이 오면 채팅에 폼을 렌더. 제출이든 텍스트든(이중 입력)
  // 다음 전송이 재개하며, 서버가 재제시하면 새 프레임이 이 상태를 덮는다.
  const [pendingForm, setPendingForm] = useState<{ formId: string; convoId: string; form: ChatFormFrame } | null>(null)

  const screens = Grid.useBreakpoint()
  // 인스펙터를 채팅과 나란히(side-by-side) 두려면 사이드바(232) + 채팅 + 인스펙터(384) 폭이 필요하다.
  // 임계값을 lg(992)로 잡으면 992~1199에서 채팅 컬럼이 ~376px로 짜부라져 헤더(아바타·이름·컨트롤)가
  // 이름 글자 단위 줄바꿈·아이콘 겹침으로 깨진다(사용자 보고 2026-07-07). side-by-side는 채팅이
  // 넉넉할 때만 — xl(1200)에서 채팅 = 1200-232-384 = 584px. 그 아래는 모바일과 동일하게 전체화면
  // 오버레이(이미 완비된 경로, 인스펙터를 꽉 차게 보여줌).
  const overlayInspector = !screens.xl

  // 에이전트 메뉴 "테스트"로 진입 시 그 에이전트 자동 선택(스펙 144 #2) — 목록 로드 후 1회 소비.
  useEffect(() => {
    if (!initialAgentId || agents.length === 0) return
    if (agents.some((a) => a.id === initialAgentId)) setActiveId(initialAgentId)
    onConsumedInitial?.()
  }, [initialAgentId, agents.length])

  const activeAgent = agents.find((a) => a.id === activeId) ?? null
  const messages = convos[activeId] || []

  // 스펙 209 P1.5 — 응답 피드백(👍/👎) 변경을 convos에 낙관 반영(FeedbackButtons가 서버 반영·실패 복원).
  const handleFeedbackChange = (i: number, fb: MessageFeedback | null) => {
    setConvos((c) => {
      const arr = (c[activeId] || []).slice()
      if (arr[i] && arr[i].role === 'ai') arr[i] = { ...arr[i], feedback: fb }
      return { ...c, [activeId]: arr }
    })
  }
  // 항상 최신 활성 에이전트 외부 id를 가리키는 박스 — 비동기 세션 로드의 레이스 가드용
  // (A 요청이 B로 전환 후 도착해 B 피커를 오염시키는 것 차단).
  const activeExtRef = useRef<string | undefined>(undefined)
  activeExtRef.current = activeAgent?.agentId
  const activeIdRef = useRef<string>('')
  activeIdRef.current = activeId ?? '' // 지식 잡 toast staleness 가드(스펙 405)

  // 적용 중 오버라이드 → 변경된 키만 담은 페이로드(코드 에이전트는 무시). 비었으면 미적용.
  const appliedOv = activeAgent ? appliedByAgent[activeAgent.id] ?? null : null
  const ovPayload =
    activeAgent && appliedOv && activeAgent.source !== 'code'
      ? // catalog(스펙 287): 노드형 노드 변경 시 풀(mcps/vectorTables/memories) 파생에 필요.
        overridePayload(appliedOv, overrideDefaults(activeAgent), { mcpItems: blocks.mcp?.items ?? [], collections })
      : {}
  // 지식 연결(스펙 405) 병합 — 저장본+기존 오버라이드+이번 세션 연결의 합집합(중복 제거).
  // **직접형 한정**(codex 405 P1①): 노드형(pipeline)은 서버가 노드 참조로 풀을 재파생해
  // vectorTables 오버라이드를 대체하므로 세션 연결이 조용히 무효 — 병합 자체를 막아 거짓 양성 차단.
  const isNodeAgent = (activeAgent?.nodes?.length ?? 0) > 0
  const wired = activeAgent && !isNodeAgent ? wiredByAgent[activeAgent.id] ?? [] : []
  if (wired.length > 0 && activeAgent && activeAgent.source !== 'code') {
    ovPayload.vectorTables = Array.from(
      new Set([...(activeAgent.vectorTables ?? []), ...((ovPayload.vectorTables as string[] | undefined) ?? []), ...wired]),
    )
  }
  const overrideActive = Object.keys(ovPayload).length > 0

  // 마운트 시 실제 에이전트 목록 로드 — 첫 번째 에이전트를 활성으로.
  useEffect(() => {
    let cancelled = false
    listAgents()
      .then((list) => {
        if (cancelled) return
        setAgents(list)
        // 시작 캐스케이드(스펙 248 후속2, 사용자 플로우): 최근 사용 에이전트를 자동 선택(재방문 시
        // 이어서), 기록 없으면 첫 항목(에이전트 1개면 그게 곧 자동 선택).
        if (list.length) {
          let recentId: string | undefined
          try {
            const recent: string[] = JSON.parse(localStorage.getItem('pg_recent_agents') || '[]')
            recentId = recent.find((id) => list.some((a) => a.id === id))
          } catch { /* 기록 없음 */ }
          setActiveId(recentId ?? list[0].id)
        }
      })
      .catch(() => {
        if (!cancelled) message.error('에이전트 목록을 불러오지 못했습니다.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 소비 표면 자가정합(스펙 080): 다른 탭/뷰에서 일어난 편집·활성화를 Playground가 모른 채
  // 마운트 스냅샷을 들고 있으면 '미반영 초안' 배지(스펙 078)가 stale하게 남는다. 목록 메타만
  // 재페치해 서버 진실원과 정합한다 — 선택(activeId)·대화(convos)·스트리밍은 보존(목록만 setAgents).
  // (1) BroadcastChannel: Agents 탭의 변경을 즉시 받는다. (2) 포커스/가시성 백스톱: 미지원 환경·
  // 놓친 메시지를 탭 복귀 시 메운다.
  useEffect(() => {
    const refetch = () => {
      listAgents().then(setAgents).catch(() => {})
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') refetch()
    }
    const unsub = onAgentsChanged(refetch)
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', refetch)
    return () => {
      unsub()
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', refetch)
    }
  }, [])

  // 세션 이어가기(스펙 055): 과거 세션 목록을 받아 피커에 채운다. 외부 agent_id로 스코프.
  // 실패는 조용히 — 피커만 빈 목록(부수 기능이 본 흐름을 막지 않게).
  const refreshSessions = () => {
    const extId = activeAgent?.agentId
    if (!extId) {
      setSessionList([])
      return
    }
    setSessionsLoading(true)
    listSessions({ agent_id: extId, limit: 20 })
      // 레이스 가드: 응답 도착 시점에도 같은 에이전트일 때만 반영(전환 후 도착분 폐기).
      .then((page) => {
        if (activeExtRef.current === extId) setSessionList(page.items)
      })
      .catch(() => {})
      .finally(() => {
        if (activeExtRef.current === extId) setSessionsLoading(false)
      })
  }

  // 활성 에이전트가 바뀌면 그 에이전트의 과거 세션을 로드(승인 후 복귀 시 마운트로도 트리거).
  useEffect(() => {
    const extId = activeAgent?.agentId
    if (!extId) {
      setSessionList([])
      return
    }
    let cancelled = false
    setSessionsLoading(true)
    listSessions({ agent_id: extId, limit: 20 })
      .then((page) => {
        if (!cancelled) setSessionList(page.items)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setSessionsLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAgent?.agentId])

  // 언마운트 시 진행 중인 스트림 중단.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  // 승인 대기 폴링(스펙 179) — pendingApproval이 설정되면 승인 상태를 주기 조회. 해소(pending 아님)되면
  // 재개 결과가 세션에 영속됐으므로 그 세션 메시지를 다시 불러 완료 턴을 채팅에 반영하고 종료.
  // 최대 시도 후 조용히 포기(대기 표시 유지 — 사용자가 세션 재열람으로 확인 가능). 라이브 push 빚(§7) 보완.
  useEffect(() => {
    if (!pendingApproval) return
    const { id: apid, convoId } = pendingApproval
    let cancelled = false
    let timer: number | undefined
    let tries = 0
    // 재개 persist 완료를 "세션 메시지 수 증가"로 감지하기 위한 기준값(이 턴 완료 전 영속 메시지 수).
    // resolve는 status를 먼저 approved로 커밋한 뒤 서버사이드로 재개·persist하므로, status만 보면
    // persist 전(레이스)에 빈 세션을 그릴 수 있다 — count 증가를 함께 확인해 완료 시점에만 반영.
    // ⚠ 스펙 180: baseline은 반드시 *완료 전*에 포착해야 한다. 인라인 승인은 프레임 도착 직후 바로
    // 승인하므로, 첫 틱을 2.5s 뒤로 미루면 그 사이 완료돼 baseline이 완료-후 카운트를 잡아 영영
    // `msgs>baseline`이 거짓이 된다 → 첫 틱을 즉시(0ms) 발화해 대기 시점의 카운트를 포착.
    let baseline: number | null = null
    const MAX = 60 // ~2.5s × 60 ≈ 2.5분
    const tick = async () => {
      if (cancelled) return
      tries += 1
      try {
        // 스펙 350: 승인 1건의 상태를 알려고 **전 목록**을 2.5초마다 받아오던 것을 단건 조회로.
        // 승인 행이 쌓일수록 폴링 한 번의 비용이 같이 커지던 구조였다(저장 누수 → 대역폭 누수 증폭).
        const found = await getApproval(apid).catch(() => null)
        if (found) {
          const sid = found.sessionId
          if (baseline === null) {
            try {
              baseline = (await getSessionMessages(sid)).length
            } catch {
              baseline = 0
            }
          }
          if (found.status && found.status !== 'pending') {
            const msgs = await getSessionMessages(sid)
            if (cancelled) return
            if (msgs.length > (baseline ?? 0)) {
              // 재개 결과가 영속됨(count 증가) → 완료 턴을 채팅에 반영하고 종료.
              setSessions((s) => ({ ...s, [convoId]: sid }))
              setConvos((c) => ({
                ...c,
                [convoId]: msgs.map((m) => ({
                  role: m.role === 'assistant' ? 'ai' : 'me',
                  text: m.content,
                  trace: (m.trace as unknown as Trace) ?? undefined,
                })),
              }))
              setPendingApproval(null)
              return
            }
            // resolved이나 아직 persist 전(레이스) → 계속 폴링.
          }
        }
      } catch {
        /* 조용히 재시도 */
      }
      if (cancelled) return
      if (tries >= MAX) {
        setPendingApproval(null)
        return
      }
      timer = window.setTimeout(tick, 2500)
    }
    timer = window.setTimeout(tick, 0) // 첫 틱 즉시 — baseline을 완료 전에 포착(빠른 인라인 승인 레이스 방지)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [pendingApproval])

  // 대화 내 인라인 승인(스펙 180) — 현재 사용자가 처리 가능한 승인 대기를 그 자리서 승인/거부.
  // canResolve: self는 요청자 본인이 항상, admin은 슈퍼유저만(서버 _may_resolve가 진짜 경계 — 여긴 표시용).
  const canResolvePending = !!pendingApproval && (pendingApproval.approver === 'self' || meIsSuperuser)
  const resolvePending = async (decision: 'approve' | 'reject') => {
    const pa = pendingApproval
    if (!pa) return
    try {
      await resolveApproval(pa.id, decision)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '승인 처리에 실패했습니다.')
      return
    }
    if (decision === 'reject') {
      // 거부는 재개가 없어(새 메시지 무) 폴링이 안 잡는다 — 대기 버블을 거부로 갱신하고 즉시 해제.
      setConvos((c) => {
        const arr = (c[pa.convoId] || []).slice()
        const li = arr.length - 1
        if (li >= 0 && arr[li].role === 'ai')
          arr[li] = { ...arr[li], text: arr[li].text + '\n\n🚫 거부됨 — 실행이 중단되었습니다.' }
        return { ...c, [pa.convoId]: arr }
      })
      setPendingApproval(null)
    }
    // approve → 화면 이동이 없어 폴링(위 useEffect)이 유지되며 완료 턴을 반영·해제한다.
  }

  // 산출물형 폼 제출(스펙 188) — 표시용 사용자 메시지("[폼 제출] …")와 함께 form 페이로드로 재개.
  const submitForm = async (values: Record<string, string>) => {
    const pf = pendingForm
    if (!pf || pf.convoId !== activeId || streaming) return
    const labelOf = (k: string) => pf.form.fields.find((f) => f.key === k)?.label || k
    const summary = Object.entries(values)
      .filter(([, v]) => v)
      .map(([k, v]) => `${labelOf(k)}=${v}`)
      .join(', ')
    await send(`[폼 제출] ${summary || '(빈 값)'}`, { formId: pf.formId, values })
  }

  // 오버라이드 패널용 카탈로그(등록 chat 모델 + 빌딩 블록). 실패는 조용히 무시 — 패널만 빈 옵션.
  useEffect(() => {
    let cancelled = false
    listModels('chat')
      .then((m) => !cancelled && setModels(m))
      .catch(() => {})
    getBlocks()
      .then((b) => !cancelled && setBlocks(b))
      .catch(() => {})
    // 조율형 위임 대상 카탈로그(스펙 122) — 문서 컬렉션. 실패는 조용히(패널 문서 그룹만 빔).
    listCollections()
      .then((c) => !cancelled && setCollections(c))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const stop = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setStreaming(false)
  }

  // 파일첨부(스펙 404) — 활성 대화의 대기 첨부(전송 시 소모·1회성). 대화 전환 시 리셋.
  const [attachments, setAttachments] = useState<ChatAttachmentDraft[]>([])
  useEffect(() => setAttachments([]), [activeId])
  const attachFiles = async (files: File[]) => {
    for (const f of files) {
      if (attachments.length >= 3) {
        message.warning('첨부는 턴당 3개까지입니다.')
        return
      }
      try {
        const a = await uploadChatAttachment(f)
        setAttachments((prev) => (prev.length >= 3 ? prev : [...prev, a]))
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    }
  }

  // 첨부→지식 저장(스펙 405, B안) — 세션 연결(오버라이드 vectorTables) + 인제스트 잡 칩.
  const patchKJob = (agentId: string, jobId: string, patch: Partial<KJob>) =>
    setKJobsByAgent((m) => ({
      ...m,
      [agentId]: (m[agentId] || []).map((j) => (j.id === jobId ? { ...j, ...patch } : j)),
    }))

  const knowledgeAttach = (files: File[]) => {
    if (files.length === 0) return
    if (files.length > 1) message.info('지식 저장은 한 번에 한 파일씩 진행합니다 — 첫 파일만 올립니다.')
    setKTarget('')
    setKNewName('')
    setKModal({ file: files[0] })
  }

  const runKnowledgeIngest = async () => {
    const file = kModal?.file
    const agentId = activeId
    const agentIsNode = (activeAgent?.nodes?.length ?? 0) > 0
    if (!file || !agentId) return
    setKModal(null)
    let colId = kTarget
    let colName = collections.find((c) => c.id === kTarget)?.name ?? kNewName.trim()
    // 잡 선등록(codex 405 P2③): 생성 단계 실패도 칩으로 남게(에러가 toast로만 스치지 않게).
    const jobId = crypto.randomUUID()
    setKJobsByAgent((m) => ({ ...m, [agentId]: [...(m[agentId] || []), { id: jobId, filename: file.name, collection: colName, status: 'ingesting' }] }))
    const stale = () => agentId !== activeIdRef.current // 화면이 딴 에이전트면 toast 억제(P2②)
    try {
      if (!colId) {
        // 새 컬렉션 — 기본 임베딩 모델로(스펙 148 이름 규칙은 서버가 검증).
        // models 상태는 chat만 로드하므로(픽커용) 임베딩은 여기서 직접 조회한다.
        const embs = await listModels('embedding')
        const emb = embs.find((m) => m.is_default) ?? embs[0]
        if (!emb) {
          patchKJob(agentId, jobId, { status: 'error', err: '임베딩 모델 없음' })
          message.error('임베딩 모델이 없습니다 — 프로바이더·모델에서 등록하세요.')
          return
        }
        const created = await createCollection({ name: kNewName.trim(), embedding_model_id: emb.id })
        colId = created.id
        colName = created.name
        setCollections((prev) => [...prev, created])
      }
      const doc = await uploadDocument(colId, file)
      // 인제스트는 비동기(parsing→ready) — 문서 status 폴링(최대 120초).
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000))
        const page = await listDocuments(colId, file.name, 5, 0)
        const row = page.items.find((d) => d.id === doc.id)
        if (row?.status === 'ready') {
          patchKJob(agentId, jobId, { status: 'ready', collection: colName })
          if (agentIsNode) {
            // 노드형은 세션 연결 미지원(풀 재파생이 오버라이드를 대체 — codex 405 P1①): 저장까지만
            // 정직하게. 연결은 노드에 검색 도구를 더하는 에이전트 편집으로.
            if (!stale()) message.info(`'${colName}'에 저장됐습니다. 노드형 에이전트는 이 자리에서 연결할 수 없어 — 에이전트 편집(노드 도구)에서 연결하면 사용할 수 있습니다.`)
          } else {
            // 세션 연결(스펙 405 핵심): 저장 에이전트 불변 — 오버라이드 vectorTables에만 합류.
            setWiredByAgent((m) => ({ ...m, [agentId]: Array.from(new Set([...(m[agentId] || []), colName])) }))
            if (!stale()) message.success(`'${colName}'에 저장돼 이번 세션에 연결됐습니다 — 계속 사용하려면 에이전트 편집에서 연결하세요.`)
          }
          return
        }
        if (row?.status === 'error') {
          patchKJob(agentId, jobId, { status: 'error', err: row.error ?? '인제스트 실패' })
          if (!stale()) message.error(`인제스트 실패: ${row.error ?? '(원인 미상)'}`)
          return
        }
      }
      patchKJob(agentId, jobId, { status: 'error', err: '시간 초과' })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      patchKJob(agentId, jobId, { status: 'error', err: msg })
      if (!stale()) message.error(msg)
    }
  }

  const send = async (text: string, form?: { formId: string; values: Record<string, string> }) => {
    if (streaming) return
    const id = activeId
    if (!id) return
    // 승인 대기 중엔 새 입력 차단(스펙 179 P3) — 그래프가 그 턴에서 멈춰 있어, 새 턴을 끼우면
    // 저장시각(created_at) 순서가 어긋나(대기 턴이 나중 저장) 대화가 뒤바뀐다. 승인/거부 후 이어간다.
    if (pendingApproval && pendingApproval.convoId === id) return
    // 폼 대기는 입력을 잠그지 않는다(이중 입력 일급, 스펙 188) — 전송 시작 시 이 대화의 폼을 내리고,
    // 서버가 재제시(form 프레임)하면 콜백이 다시 세운다.
    setPendingForm((p) => (p && p.convoId === id ? null : p))

    // 직전 대화로 백엔드 메시지 배열 구성 — me→user, ai→assistant, 빈 텍스트 제외.
    const prior = convos[id] || []
    const apiMessages: ChatMessage[] = prior
      .filter((m) => m.text.trim())
      .map((m) => ({ role: m.role === 'me' ? 'user' : 'assistant', content: m.text }))
    apiMessages.push({ role: 'user', content: text })

    // 파일첨부 스냅샷+소모(스펙 404, 1회성). 원문 주입본은 서버가 영속 — UI는 칩 표기만.
    const sendAtts = attachments
    setAttachments([])
    const meText =
      sendAtts.length > 0 ? `${text}\n📎 ${sendAtts.map((a) => a.filename).join(' · ')}` : text
    // 사용자 턴 + 빈 ai 플레이스홀더 추가.
    setConvos((c) => ({
      ...c,
      [id]: [...(c[id] || []), { role: 'me', text: meText }, { role: 'ai', text: '' }],
    }))

    const appendToLastAi = (fn: (prev: ChatMsg) => ChatMsg) => {
      setConvos((c) => {
        const arr = (c[id] || []).slice()
        const last = arr[arr.length - 1]
        if (last && last.role === 'ai') arr[arr.length - 1] = fn(last)
        return { ...c, [id]: arr }
      })
    }

    const controller = new AbortController()
    controllerRef.current = controller
    setStreaming(true)
    // A2A 루프백 모드(스펙 155): 노출 에이전트를 외부 소비자처럼 /agents/{id}/a2a로 호출.
    // 단발 메시지(세션/히스토리/오버라이드/trace 미전달 — 우리 A2A 서빙이 안 넘김).
    const useA2A = !!activeAgent && isA2AExposed(activeAgent) && !!a2aByAgent[id]
    try {
      if (useA2A) {
        // 인스펙터를 새 A2A 턴으로 이동(codex 경계 #2): A2A 경로는 trace를 안 주므로 갱신하지 않으면
        // 인스펙터가 직전 direct 턴의 trace를 stale 표시한다. 새 ai 턴(= prior 뒤 index)을 선택해
        // 빈 상태("이 턴엔 trace 없음")를 보이게 한다.
        setSelectedTurn(prior.length + 1)
        await streamChatA2A(
          id,
          text,
          (t) => appendToLastAi((prev) => ({ ...prev, text: prev.text + t })),
          controller.signal,
        )
        setStreaming(false)
        return
      }
      await streamChat(
        id,
        apiMessages,
        {
          onToken: (t) => appendToLastAi((prev) => ({ ...prev, text: prev.text + t })),
          // 사고 과정(스펙 410·413) — 본문과 별개로 **노드별** 누적. 노드가 순차 실행돼 델타가
          // 노드별로 몰려 오므로, 마지막 스텝이 같은 노드면 이어붙이고 아니면 새 스텝(순서 보존).
          onReasoning: (t, node) =>
            appendToLastAi((prev) => {
              const steps = [...(prev.reasoningSteps ?? [])]
              const key = node ?? ''
              const last = steps[steps.length - 1]
              if (last && last.node === key) steps[steps.length - 1] = { node: key, text: last.text + t }
              else steps.push({ node: key, text: t })
              return { ...prev, reasoningSteps: steps }
            }),
          onSession: (sid) => setSessions((s) => ({ ...s, [id]: sid })),
          // 승인 대기 프레임(스펙 179) — 이 턴의 승인 id를 잡아 폴링 시작(아래 useEffect).
          onApproval: (apid, approver) => setPendingApproval({ id: apid, convoId: id, approver }),
          // 산출물형(스펙 188) — 폼 프레임은 입력 위 폼 렌더, artifact는 그 턴 메시지에 카드로.
          onForm: (formId, f) => setPendingForm({ formId, convoId: id, form: f }),
          onArtifact: (artifact) => appendToLastAi((prev) => ({ ...prev, artifact })),
          // 스펙 209 P1.5 — 저장된 assistant id를 이 턴 메시지에 부착(피드백 버튼 노출 조건).
          onMessageId: (mid) => appendToLastAi((prev) => ({ ...prev, id: mid })),
          onTrace: (tr) => {
            const trace = tr as unknown as Trace
            setConvos((c) => {
              const arr = (c[id] || []).slice()
              const lastIdx = arr.length - 1
              const last = arr[lastIdx]
              if (last && last.role === 'ai') arr[lastIdx] = { ...last, trace }
              // selectedTurn은 갱신해 둔다(인스펙터를 직접 열면 최신 턴을 보이도록) —
              // 단, 자동으로 열지는 않는다. 매 턴 끼어들어 불편(사용자 피드백).
              setSelectedTurn(lastIdx)
              return { ...c, [id]: arr }
            })
            // trace는 양 백엔드 경로에서 '턴 완료' 직후에만 나온다(바로 뒤 [DONE]). 그러니 여기서
            // 스피너를 멈춘다 — [DONE]/소켓 종료가 늦거나 안 와도(원격 업스트림이 연결을 안 닫는 등)
            // 전송 버튼이 계속 도는 문제를 막는다(사용자 피드백 #7). finally가 다시 false 처리해도 무해.
            setStreaming(false)
          },
          // 스펙 314: [DONE]=턴 논리 완료. 스트림은 이후 백그라운드 기억 저장 완료(event: memory)를
          // 기다리며 열려 있을 수 있으므로, 완료 표시(스피너 해제)는 여기서도 확실히 한다.
          onDone: () => setStreaming(false),
          // 스펙 314: 백그라운드 자동 기억 저장 완료 — 그 mid의 턴을 **조용히** 패치(pending→saved).
          // 이벤트가 늦게 와 사용자가 딴 세션/화면이면 그 mid가 목록에 없어 no-op(조용히 무시).
          onMemory: (mid, memorySaved) => {
            setConvos((c) => {
              const arr = (c[id] || []).slice()
              const idx = arr.findIndex((m) => m.role === 'ai' && m.id === mid)
              if (idx < 0) return c // 그 턴이 현재 화면에 없음 → 조용히 무시(토스트·포커스 이동 없음)
              const cur = arr[idx]
              if (!cur.trace) return c
              arr[idx] = {
                ...cur,
                trace: { ...cur.trace, memorySaved: memorySaved as Trace['memorySaved'], memoryPending: false },
              }
              return { ...c, [id]: arr }
            })
          },
        },
        controller.signal,
        sessions[id],
        ovPayload, // 세션 한정 오버라이드(변경된 키만; 빈 객체면 streamChat이 보내지 않음)
        form, // 산출물형 폼 제출(스펙 188) — 텍스트 입력이면 undefined
        pinnedVersions[id], // 버전 미리보기(스펙 243) — undefined=활성(무회귀)
        sendAtts.map((a) => ({ filename: a.filename, text: a.text })), // 파일첨부(스펙 404)
      )
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        /* 사용자가 취소 — 무시 */
      } else {
        const msg = e instanceof Error ? e.message : String(e)
        appendToLastAi((prev) => ({ ...prev, text: prev.text + `\n[오류] ${msg}` }))
      }
    } finally {
      // 스펙 314: 스트림이 백그라운드 기억 저장까지 열려 있다 늦게 resolve될 수 있다. 그 사이 사용자가
      // 새 메시지를 보내 controllerRef가 교체됐으면, 이 오래된 스트림의 정리가 새 턴의 상태(전역
      // streaming·controller)를 건드리면 안 된다 — 자기 controller일 때만 정리(교체됐으면 no-op).
      if (controllerRef.current === controller) {
        controllerRef.current = null
        setStreaming(false)
      }
    }
  }

  const switchAgent = (id: string) => {
    stop()
    setActiveId(id)
    // 서랍 열린 채 에이전트를 바꾸면 닫는다(후속28, 사용자) — 열린 서랍은 이전 에이전트의
    // 오버라이드 폼이라 새 에이전트와 안 맞는 상태를 노출하게 됨.
    setOverridePanelOpen(false)
  }

  // 지식 연결 정리(스펙 405, codex P1②) — "이번 세션 연결"의 수명을 세션과 일치시킨다:
  // 새 대화·과거 세션 전환은 다른 세션이므로 연결·잡 칩을 비운다(에이전트 수명으로 새지 않게).
  const clearKnowledgeWiring = (agentId: string) => {
    setWiredByAgent((m) => ({ ...m, [agentId]: [] }))
    setKJobsByAgent((m) => ({ ...m, [agentId]: [] }))
  }

  // "새 대화" — 활성 에이전트의 대화·세션을 비워 처음부터 다시 시작한다(스펙 032: userId 잠금 분리).
  const resetConversation = () => {
    stop()
    clearKnowledgeWiring(activeId)
    // 진행 중인 세션 로드가 리셋된 대화를 되살리지 않도록 시퀀스를 무효화(codex 지적).
    sessionLoadSeqRef.current++
    setConvos((c) => ({ ...c, [activeId]: [] }))
    setSessions((s) => {
      const n = { ...s }
      delete n[activeId]
      return n
    })
    setSelectedTurn(null)
    setInspectorOpen(false)
    // 세션 칩 힌트("클릭하여 다른 세션 선택"/"첫 세션…")가 최신 목록 기준이 되도록(스펙 248 후속9 —
    // 드롭다운 열 때만 리로드하면 방금 만든 세션이 안 잡혀 문구가 틀린다).
    refreshSessions()
  }

  // 버전 미리보기 선택(스펙 243) — 바꾸면 새 대화로 리셋(한 대화에 버전 혼재 방지·오버라이드 결과 동일).
  const pinVersion = (v?: string) => {
    setPinnedVersions((m) => ({ ...m, [activeId]: v }))
    resetConversation()
  }

  // 과거 세션 선택 → DB 메시지를 불러와 대화 복원 + session_id를 활성 세션으로 고정(스펙 055).
  // 이어 보내기는 기존 send()가 sessions[id]를 그대로 써 같은 세션에 쌓인다. 컨텍스트도 복원된
  // convos에서 재구성되어 일관. 진행 중 스트림이 있으면 먼저 멈춘다(025 리셋 흐름과 동일 안전).
  const loadSession = (sid: string) => {
    if (!activeId || sid === sessions[activeId]) return
    // 방어 가드(codex): 피커는 활성 에이전트 세션만 보여주지만, 늦게 도착한 다른 에이전트
    // 목록이 섞였을 가능성을 차단 — 선택 세션이 활성 에이전트 소속이 아니면 무시.
    const picked = sessionList.find((s) => s.id === sid)
    if (picked && activeAgent && picked.agentId !== activeAgent.agentId) return
    stop()
    clearKnowledgeWiring(activeId) // 과거 세션은 다른 세션 — 이번-세션 연결을 승계하지 않는다(스펙 405).
    const seq = ++sessionLoadSeqRef.current
    const targetId = activeId // 로드 중 에이전트가 바뀌어도 원 에이전트 대화에만 반영.
    const prevSid = sessions[targetId] // 실패 시 롤백용(undefined면 새 세션 상태로 복귀).
    // session_id를 먼저 고정 — 메시지 로드 완료 전에 전송해도 같은(올바른) 세션에 쌓이게.
    setSessions((s) => ({ ...s, [targetId]: sid }))
    getSessionMessages(sid)
      .then((msgs) => {
        if (seq !== sessionLoadSeqRef.current) return // 더 최신 선택이 있으면 폐기(레이스).
        if (overrideActive) {
          // 스펙 134 — 오버라이드는 세션 속성이 아니라 "지금 적용 중" 상태: 과거 세션에 이어 쓰면 이전
          // 턴들과 설정이 다를 수 있음을 환기(로드 **성공 시에만** — 실패 시 뜨면 오해 소지).
          // 턴별 진실은 인스펙터 "오버라이드" 섹션이 영구 기록.
          message.info('오버라이드 적용 중 — 이 세션의 이전 턴들과 설정이 다를 수 있습니다.')
        }
        const mapped: ChatMsg[] = msgs.map((m) => ({
          role: m.role === 'assistant' ? 'ai' : 'me',
          text: m.content,
          trace: (m.trace as unknown as Trace) ?? undefined,
          id: m.id ?? undefined, // 스펙 209 P1.5 — 피드백 부착용(assistant만 서버가 채움)
          feedback: m.feedback ?? null,
        }))
        setConvos((c) => ({ ...c, [targetId]: mapped }))
        setSelectedTurn(null)
        setInspectorOpen(false)
      })
      .catch(() => {
        // 로드 실패 → 낙관적으로 고정한 session_id를 원복(이전 세션에 묶인 채 남지 않게, codex).
        if (seq === sessionLoadSeqRef.current) {
          setSessions((s) => {
            const n = { ...s }
            if (prevSid === undefined) delete n[targetId]
            else n[targetId] = prevSid
            return n
          })
        }
        message.error('세션을 불러오지 못했습니다.')
      })
  }

  // 오버라이드 적용 → 세션 리셋 후 새 설정으로 시작(변경 시 채팅 재시작, 스펙 025).
  const applyOverrides = (ov: Overrides) => {
    setAppliedByAgent((m) => ({ ...m, [activeId]: ov }))
    setOverridePanelOpen(false)
    resetConversation()
  }
  // 오버라이드 해제 → 저장 설정으로 복귀, 역시 세션 리셋.
  const clearOverrides = () => {
    setAppliedByAgent((m) => {
      const n = { ...m }
      delete n[activeId]
      return n
    })
    setOverridePanelOpen(false)
    resetConversation()
  }

  // Clicking a turn's "인스펙터" chip opens the panel on that turn.
  const openInspector = (i: number) => {
    setSelectedTurn(i)
    setInspectorOpen(true)
  }

  const selectedMsg = selectedTurn != null ? messages[selectedTurn] : null
  // 턴 번호(스펙 205) — 배열 인덱스가 아니라 그 시점까지의 user 메시지 수(질문 순번). 1문답="턴 1".
  const selectedTurnNo = selectedTurn != null
    ? messages.slice(0, selectedTurn + 1).filter((m) => m.role === 'me').length
    : 1

  // 오버라이드 서랍(스펙 248 후속17) — DebugChat의 헤더 아래 영역에 렌더(U 손잡이 바로 아래서 내려옴).
  // 후속19(사용자): 닫기도 같은 손잡이로 — 서랍이 열리면 손잡이가 서랍 앞면 하단(우측)으로 내려온
  // 것처럼, 하단 U를 당기면(클릭) 서랍이 올라간다. 좌측 X는 제거(여닫이 입구 일원화).
  const overridePanelNode = (
    <>
      <Modal
        open={!!kModal}
        title="지식으로 저장 (RAG)"
        okText="저장"
        cancelText="취소"
        onCancel={() => setKModal(null)}
        onOk={() => void runKnowledgeIngest()}
        okButtonProps={{ disabled: !kTarget && !kNewName.trim() }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            📎 <b>{kModal?.file.name}</b> — 문서를 컬렉션에 저장하고 이번 세션에 연결합니다.
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
              저장된 문서는 지식 자산으로 남습니다. 연결은 이번 세션 동안 유지 — 계속 사용하려면 에이전트 편집에서 연결하세요.
            </div>
          </div>
          <Select
            placeholder="기존 컬렉션 선택 (또는 아래에 새 이름 입력)"
            value={kTarget || undefined}
            onChange={(v) => setKTarget(v)}
            allowClear
            onClear={() => setKTarget('')}
            options={collections
              .filter((c) => (c.kind ?? 'document') === 'document')
              .map((c) => ({ value: c.id, label: c.name }))}
          />
          {!kTarget && (
            <Input
              placeholder="새 컬렉션 이름 (영소문자·숫자·대시)"
              value={kNewName}
              onChange={(e) => setKNewName(e.target.value)}
            />
          )}
        </div>
      </Modal>
      <OverridePanel
        open={overridePanelOpen}
        agent={activeAgent}
        models={models}
        blocks={blocks}
        agents={agents}
        collections={collections}
        applied={appliedOv}
        onApply={applyOverrides}
        onClear={clearOverrides}
        onClose={() => setOverridePanelOpen(false)}
        footer={
          // 모바일(후속21, 사용자): 바깥 손잡이는 70vh+헤더 탓에 화면 밖 — 드로어 안 하단 우측으로.
          !screens.md ? (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="small" icon={<Icon name="up" size={11} />} onClick={() => setOverridePanelOpen(false)} aria-label="오버라이드 닫기">
                닫기
              </Button>
            </div>
          ) : undefined
        }
        bottomHandle={
          // 데탑(후속22, 사용자: 0.5초 늦게 나옴): 패널에 부착돼 서랍과 함께 이동 — 지연 0.
          screens.md ? (
            <button
              onClick={() => setOverridePanelOpen(false)}
              aria-label="오버라이드 닫기"
              title="서랍을 닫습니다"
              style={{
                position: 'absolute', right: 28, bottom: 0, transform: 'translateY(100%)',
                pointerEvents: 'auto', // 래퍼가 pointer-events:none(rc-drawer) — 패널 밖 손잡이는 명시 복원
                display: 'flex', alignItems: 'center', gap: 5, padding: '3px 14px 5px',
                border: '1px solid var(--color-border-secondary)', borderTop: 'none',
                borderRadius: '0 0 12px 12px',
                background: 'var(--color-bg-container)', color: 'var(--color-text-tertiary)',
                fontSize: 12, cursor: 'pointer', font: 'inherit',
                boxShadow: '0 2px 4px rgba(0,0,0,0.04)',
                transition: 'transform .15s ease',
              }}
              // 감성(후속23→24 수정): ∧=밀어 올리기 — 호버 시 2px 올라가 "올릴 준비".
              // bottom 고정 배치라 margin-top은 무효(후속23의 첫 시도가 무동작) — transform으로.
              onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(calc(100% - 2px))' }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(100%)' }}
            >
              <Icon name="up" size={11} />
              오버라이드
            </button>
          ) : undefined
        }
      />
    </>
  )

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', background: 'var(--color-bg-container)' }}>
      {inspectorOpen && !overlayInspector ? (
        /* 도킹 인스펙터를 antd Splitter로(스펙 204) — 수제 aside 고정폭 대신 드래그 리사이즈.
           채팅‖인스펙터 분할은 Splitter.Panel이 폭을 소유한다(Inspector aside는 width 100%). */
        <Splitter style={{ flex: 1, minHeight: 0 }}>
          <Splitter.Panel min="35%">
            {/* Splitter.Panel은 블록 컨테이너 — DebugChat 루트(flex:1)가 높이를 받도록 flex 행 복원
               (없으면 내용이 위로 붙고 입력창이 바닥 고정을 잃음 — 사용자 발견). */}
            <div style={{ height: '100%', display: 'flex', minWidth: 0 }}>
      <DebugChat
        agent={activeAgent}
        agents={agents}
        onSwitchAgent={switchAgent}
        sessions={sessionList}
        currentSessionId={sessions[activeId]}
        sessionsLoading={sessionsLoading}
        onPickSession={loadSession}
        onReloadSessions={refreshSessions}
        overridePanel={overridePanelNode}
        overrideOpen={overridePanelOpen}
        messages={messages}
        onFeedbackChange={handleFeedbackChange}
        streaming={streaming}
        awaitingApproval={!!pendingApproval && pendingApproval.convoId === activeId}
        approvalCanResolve={canResolvePending && pendingApproval?.convoId === activeId}
        approvalKind={pendingApproval?.approver === 'self' ? 'self' : 'admin'}
        onResolveApproval={resolvePending}
        pendingForm={pendingForm && pendingForm.convoId === activeId ? pendingForm : null}
        onSubmitForm={submitForm}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        attachments={attachments}
        onAttachFiles={attachFiles}
        onRemoveAttachment={(i) => setAttachments((prev) => prev.filter((_, x) => x !== i))}
        knowledgeJobs={kJobsByAgent[activeId] ?? []}
        onAttachKnowledge={knowledgeAttach}
        onDismissKnowledgeJob={(i) =>
          setKJobsByAgent((m) => ({ ...m, [activeId]: (m[activeId] || []).filter((_, x) => x !== i) }))
        }
        onSend={send}
        onStop={stop}
        onResetConversation={resetConversation}
        inspectorOpen={inspectorOpen}
        overrideActive={overrideActive}
        onToggleOverrides={() => setOverridePanelOpen((o) => !o)}
        a2aMode={!!a2aByAgent[activeId]}
        onToggleA2A={(v) => setA2aByAgent((m) => ({ ...m, [activeId]: v }))}
        pinnedVersion={pinnedVersions[activeId]}
        onPinVersion={pinVersion}
      />
            </div>
          </Splitter.Panel>
          <Splitter.Panel defaultSize={384} min={300} max={720}>
            <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurnNo - 1} onClose={() => setInspectorOpen(false)} />
          </Splitter.Panel>
        </Splitter>
      ) : (
        <>
      <DebugChat
        agent={activeAgent}
        agents={agents}
        onSwitchAgent={switchAgent}
        sessions={sessionList}
        currentSessionId={sessions[activeId]}
        sessionsLoading={sessionsLoading}
        onPickSession={loadSession}
        onReloadSessions={refreshSessions}
        overridePanel={overridePanelNode}
        overrideOpen={overridePanelOpen}
        messages={messages}
        onFeedbackChange={handleFeedbackChange}
        streaming={streaming}
        awaitingApproval={!!pendingApproval && pendingApproval.convoId === activeId}
        approvalCanResolve={canResolvePending && pendingApproval?.convoId === activeId}
        approvalKind={pendingApproval?.approver === 'self' ? 'self' : 'admin'}
        onResolveApproval={resolvePending}
        pendingForm={pendingForm && pendingForm.convoId === activeId ? pendingForm : null}
        onSubmitForm={submitForm}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        attachments={attachments}
        onAttachFiles={attachFiles}
        onRemoveAttachment={(i) => setAttachments((prev) => prev.filter((_, x) => x !== i))}
        knowledgeJobs={kJobsByAgent[activeId] ?? []}
        onAttachKnowledge={knowledgeAttach}
        onDismissKnowledgeJob={(i) =>
          setKJobsByAgent((m) => ({ ...m, [activeId]: (m[activeId] || []).filter((_, x) => x !== i) }))
        }
        onSend={send}
        onStop={stop}
        onResetConversation={resetConversation}
        inspectorOpen={inspectorOpen}
        overrideActive={overrideActive}
        onToggleOverrides={() => setOverridePanelOpen((o) => !o)}
        a2aMode={!!a2aByAgent[activeId]}
        onToggleA2A={(v) => setA2aByAgent((m) => ({ ...m, [activeId]: v }))}
        pinnedVersion={pinnedVersions[activeId]}
        onPinVersion={pinVersion}
      />
          {inspectorOpen && overlayInspector ? (
            // 좁은 폭(lg 미만): 인스펙터를 전체화면 오버레이로 — 채팅과 나란히 두면 양쪽이 짜부라진다.
            // antd Drawer로 통일(스펙 204) — 수제 fixed div 제거, 애니메이션·Escape·포커스는 antd가.
            <Drawer
              open
              placement="right"
              size="100%"
              closable={false}
              onClose={() => setInspectorOpen(false)}
              styles={{ body: { padding: 0 } }}
            >
              <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurnNo - 1} onClose={() => setInspectorOpen(false)} fullWidth />
            </Drawer>
          ) : null}
        </>
      )}
    </div>
  )
}
