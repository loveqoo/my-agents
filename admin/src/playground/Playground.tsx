/* my-agents debug console — app shell. Loads real agents, drives the real
   streaming chat API, and links each assistant turn → the Inspector from the
   real execution trace. 3-pane: agent picker (in header) + debug chat + Inspector. */
import { useEffect, useRef, useState } from 'react'
import { message, Grid } from 'antd'
import { DebugChat } from './DebugChat'
import { Inspector } from './Inspector'
import { OverridePanel, overrideDefaults, overridePayload, type Overrides } from './OverridePanel'
import type { ChatMsg, Trace } from './agentData'
import type { Agent, BlockCategory, Session } from '../admin/mockData'
import {
  listAgents, streamChat, getBlocks, listModels, listSessions, getSessionMessages,
  type ChatMessage, type Model,
} from '../api'

export function Playground() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [activeId, setActiveId] = useState('')
  const [convos, setConvos] = useState<Record<string, ChatMsg[]>>({})
  const [sessions, setSessions] = useState<Record<string, string>>({})
  // 세션 이어가기(스펙 055): 활성 에이전트의 과거 세션 목록 + 로딩 상태.
  const [sessionList, setSessionList] = useState<Session[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  // mem0 user_id 축은 서버가 로그인 유저에서 도출한다(스펙 032) — Playground에 수동 입력 없음.
  // 오버라이드 패널(스펙 025) — 카탈로그(모델·블록) + 에이전트별 적용 오버라이드.
  const [models, setModels] = useState<Model[]>([])
  const [blocks, setBlocks] = useState<Record<string, BlockCategory>>({})
  const [overridePanelOpen, setOverridePanelOpen] = useState(false)
  const [appliedByAgent, setAppliedByAgent] = useState<Record<string, Overrides>>({})
  const controllerRef = useRef<AbortController | null>(null)
  // 세션 로드 레이스 가드(스펙 055): 늦게 도착한 응답이 최신 선택을 덮어쓰지 않게 하는 시퀀스.
  const sessionLoadSeqRef = useRef(0)

  const screens = Grid.useBreakpoint()
  // 인스펙터를 채팅과 나란히(side-by-side) 두려면 사이드바 + 채팅 + 인스펙터(384px)가
  // 모두 들어갈 폭이 필요하다. lg(992) 미만에서는 채팅 컬럼이 184px 수준으로 짜부라져
  // 헤더 컨트롤(아바타·userId·버튼)이 인스펙터 헤더로 흘러넘쳐 "턴 인스펙터" 타이틀·아이콘과
  // 겹친다(어중간한 폭 버그, #9). 그래서 lg 미만에서는 모바일과 동일하게 전체화면 오버레이로 띄운다.
  const overlayInspector = !screens.lg

  const activeAgent = agents.find((a) => a.id === activeId) ?? null
  const messages = convos[activeId] || []
  // 항상 최신 활성 에이전트 외부 id를 가리키는 박스 — 비동기 세션 로드의 레이스 가드용
  // (A 요청이 B로 전환 후 도착해 B 피커를 오염시키는 것 차단).
  const activeExtRef = useRef<string | undefined>(undefined)
  activeExtRef.current = activeAgent?.agentId

  // 적용 중 오버라이드 → 변경된 키만 담은 페이로드(코드 에이전트는 무시). 비었으면 미적용.
  const appliedOv = activeAgent ? appliedByAgent[activeAgent.id] ?? null : null
  const ovPayload =
    activeAgent && appliedOv && activeAgent.source !== 'code'
      ? overridePayload(appliedOv, overrideDefaults(activeAgent))
      : {}
  const overrideActive = Object.keys(ovPayload).length > 0
  // 시스템 프롬프트 뷰어는 적용된 오버라이드를 우선 반영(화면=실제 정합, 학습 025).
  const effectiveSystemPrompt = (ovPayload.systemPrompt as string | undefined) ?? activeAgent?.systemPrompt

  // 마운트 시 실제 에이전트 목록 로드 — 첫 번째 에이전트를 활성으로.
  useEffect(() => {
    let cancelled = false
    listAgents()
      .then((list) => {
        if (cancelled) return
        setAgents(list)
        if (list.length) setActiveId(list[0].id)
      })
      .catch(() => {
        if (!cancelled) message.error('에이전트 목록을 불러오지 못했습니다.')
      })
    return () => {
      cancelled = true
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

  // 오버라이드 패널용 카탈로그(등록 chat 모델 + 빌딩 블록). 실패는 조용히 무시 — 패널만 빈 옵션.
  useEffect(() => {
    let cancelled = false
    listModels('chat')
      .then((m) => !cancelled && setModels(m))
      .catch(() => {})
    getBlocks()
      .then((b) => !cancelled && setBlocks(b))
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

  const send = async (text: string) => {
    if (streaming) return
    const id = activeId
    if (!id) return

    // 직전 대화로 백엔드 메시지 배열 구성 — me→user, ai→assistant, 빈 텍스트 제외.
    const prior = convos[id] || []
    const apiMessages: ChatMessage[] = prior
      .filter((m) => m.text.trim())
      .map((m) => ({ role: m.role === 'me' ? 'user' : 'assistant', content: m.text }))
    apiMessages.push({ role: 'user', content: text })

    // 사용자 턴 + 빈 ai 플레이스홀더 추가.
    setConvos((c) => ({
      ...c,
      [id]: [...(c[id] || []), { role: 'me', text }, { role: 'ai', text: '' }],
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
    try {
      await streamChat(
        id,
        apiMessages,
        {
          onToken: (t) => appendToLastAi((prev) => ({ ...prev, text: prev.text + t })),
          onSession: (sid) => setSessions((s) => ({ ...s, [id]: sid })),
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
        },
        controller.signal,
        sessions[id],
        ovPayload, // 세션 한정 오버라이드(변경된 키만; 빈 객체면 streamChat이 보내지 않음)
      )
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        /* 사용자가 취소 — 무시 */
      } else {
        const msg = e instanceof Error ? e.message : String(e)
        appendToLastAi((prev) => ({ ...prev, text: prev.text + `\n[오류] ${msg}` }))
      }
    } finally {
      controllerRef.current = null
      setStreaming(false)
    }
  }

  const switchAgent = (id: string) => {
    stop()
    setActiveId(id)
    setShowPrompt(false)
  }

  // "새 대화" — 활성 에이전트의 대화·세션을 비워 처음부터 다시 시작한다(스펙 032: userId 잠금 분리).
  const resetConversation = () => {
    stop()
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
    const seq = ++sessionLoadSeqRef.current
    const targetId = activeId // 로드 중 에이전트가 바뀌어도 원 에이전트 대화에만 반영.
    const prevSid = sessions[targetId] // 실패 시 롤백용(undefined면 새 세션 상태로 복귀).
    // session_id를 먼저 고정 — 메시지 로드 완료 전에 전송해도 같은(올바른) 세션에 쌓이게.
    setSessions((s) => ({ ...s, [targetId]: sid }))
    getSessionMessages(sid)
      .then((msgs) => {
        if (seq !== sessionLoadSeqRef.current) return // 더 최신 선택이 있으면 폐기(레이스).
        const mapped: ChatMsg[] = msgs.map((m) => ({
          role: m.role === 'assistant' ? 'ai' : 'me',
          text: m.content,
          trace: (m.trace as unknown as Trace) ?? undefined,
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

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', background: 'var(--color-bg-container)' }}>
      <DebugChat
        agent={activeAgent}
        agents={agents}
        onSwitchAgent={switchAgent}
        sessions={sessionList}
        currentSessionId={sessions[activeId]}
        sessionsLoading={sessionsLoading}
        onPickSession={loadSession}
        onReloadSessions={refreshSessions}
        messages={messages}
        streaming={streaming}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        onSend={send}
        onStop={stop}
        canResetConversation={messages.length > 0}
        onResetConversation={resetConversation}
        showPrompt={showPrompt}
        onTogglePrompt={() => setShowPrompt((s) => !s)}
        effectiveSystemPrompt={effectiveSystemPrompt}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((o) => !o)}
        overrideActive={overrideActive}
        onToggleOverrides={() => setOverridePanelOpen((o) => !o)}
      />
      <OverridePanel
        open={overridePanelOpen}
        agent={activeAgent}
        models={models}
        blocks={blocks}
        applied={appliedOv}
        onApply={applyOverrides}
        onClear={clearOverrides}
        onClose={() => setOverridePanelOpen(false)}
      />
      {inspectorOpen ? (
        overlayInspector ? (
          // 좁은 폭(lg 미만): 인스펙터를 전체화면 오버레이로 — 채팅과 나란히 두면 양쪽이 짜부라진다.
          <div style={{ position: 'fixed', inset: 0, zIndex: 1200, background: 'var(--color-bg-container)' }}>
            <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurn || 0} onClose={() => setInspectorOpen(false)} fullWidth />
          </div>
        ) : (
          <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurn || 0} onClose={() => setInspectorOpen(false)} />
        )
      ) : null}
    </div>
  )
}
