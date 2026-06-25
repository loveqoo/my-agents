/* my-agents debug console — app shell. Loads real agents, drives the real
   streaming chat API, and links each assistant turn → the Inspector from the
   real execution trace. 3-pane: agent picker (in header) + debug chat + Inspector. */
import { useEffect, useRef, useState } from 'react'
import { message, Grid } from 'antd'
import { DebugChat } from './DebugChat'
import { Inspector } from './Inspector'
import { OverridePanel, overrideDefaults, overridePayload, type Overrides } from './OverridePanel'
import type { ChatMsg, Trace } from './agentData'
import type { Agent, BlockCategory } from '../admin/mockData'
import { listAgents, listUserIds, streamChat, getBlocks, listModels, type ChatMessage, type Model } from '../api'

export function Playground() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [activeId, setActiveId] = useState('')
  const [convos, setConvos] = useState<Record<string, ChatMsg[]>>({})
  const [sessions, setSessions] = useState<Record<string, string>>({})
  const [streaming, setStreaming] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  // 메모리 스코프 테스트용: 비우면 세션 단기, 값이 있으면 그 유저로 세션 가로지르는 장기 기억.
  const [userId, setUserId] = useState('')
  // 그동안 대화에 쓰인 userId 목록(최근순) — 헤더 AutoComplete 선택지(스펙 021).
  const [userIds, setUserIds] = useState<string[]>([])
  // 오버라이드 패널(스펙 025) — 카탈로그(모델·블록) + 에이전트별 적용 오버라이드.
  const [models, setModels] = useState<Model[]>([])
  const [blocks, setBlocks] = useState<Record<string, BlockCategory>>({})
  const [overridePanelOpen, setOverridePanelOpen] = useState(false)
  const [appliedByAgent, setAppliedByAgent] = useState<Record<string, Overrides>>({})
  const controllerRef = useRef<AbortController | null>(null)

  const screens = Grid.useBreakpoint()
  // 인스펙터를 채팅과 나란히(side-by-side) 두려면 사이드바 + 채팅 + 인스펙터(384px)가
  // 모두 들어갈 폭이 필요하다. lg(992) 미만에서는 채팅 컬럼이 184px 수준으로 짜부라져
  // 헤더 컨트롤(아바타·userId·버튼)이 인스펙터 헤더로 흘러넘쳐 "턴 인스펙터" 타이틀·아이콘과
  // 겹친다(어중간한 폭 버그, #9). 그래서 lg 미만에서는 모바일과 동일하게 전체화면 오버레이로 띄운다.
  const overlayInspector = !screens.lg

  const activeAgent = agents.find((a) => a.id === activeId) ?? null
  const messages = convos[activeId] || []

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

  // 언마운트 시 진행 중인 스트림 중단.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  // 과거 userId 목록 로드(실패는 조용히 무시 — 자유 입력은 그대로 됨).
  useEffect(() => {
    let cancelled = false
    listUserIds()
      .then((ids) => {
        if (!cancelled) setUserIds(ids)
      })
      .catch(() => {})
    return () => {
      cancelled = true
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
        userId.trim() || undefined,
        ovPayload, // 세션 한정 오버라이드(변경된 키만; 빈 객체면 streamChat이 보내지 않음)
      )
      // 방금 쓴 userId를 목록 맨 앞으로(최근순) — 다음 로드 전에도 드롭다운에 보이게.
      const uid = userId.trim()
      if (uid) setUserIds((ids) => [uid, ...ids.filter((x) => x !== uid)])
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

  // "새 대화" — 활성 에이전트의 대화·세션을 비워 userId 입력을 다시 풀어준다(스펙 021).
  // userId 자체는 유지 → 살짝 고쳐 다시 시작하기 쉽도록.
  const resetConversation = () => {
    stop()
    setConvos((c) => ({ ...c, [activeId]: [] }))
    setSessions((s) => {
      const n = { ...s }
      delete n[activeId]
      return n
    })
    setSelectedTurn(null)
    setInspectorOpen(false)
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
        messages={messages}
        streaming={streaming}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        onSend={send}
        onStop={stop}
        userId={userId}
        onUserIdChange={setUserId}
        userIds={userIds}
        userIdLocked={messages.length > 0}
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
