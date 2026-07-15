/* AgentsView 데이터 오케스트레이션 훅(스펙 185 Phase B) — 목록·레퍼런스 데이터와 12개 뮤테이션을
   한 곳에. 컴포넌트는 UI(선택·드로워·폼·필터)와 **성공 토스트·네비게이션**만 소유한다.

   설계 규칙(deep-reasoner 분석):
   - **뮤테이션은 데이터만**: API 호출 + 배열 반영 + notify. Agent 반환(or void), 실패는 **throw**
     (토스트/네비 없음). 성공 토스트는 커스텀 플로팅 Alert이라 컴포넌트가, 실패 문구도 호출부가 결정
     (fork/revert는 message.warning 등 지점별 상이) → 훅은 표면을 강요하지 않는다.
   - **agents는 useState**(prepend/filter/replace 로컬 뮤테이션 필요 → useAsyncData 불가). blocks/models/
     collections는 마운트 후 불변 → useAsyncData.
   - **notify 비대칭 보존**(스펙 080): 초기 목록 로드는 setAgents 직접(신호 안 쏨 — 재페치 루프 방지),
     뮤테이션만 notifyAgentsChanged. */
import { useEffect, useState } from 'react'
import { message } from 'antd'
import { useAsyncData } from '../../../hooks'
import { notifyAgentsChanged } from '../../../agentsBus'
import {
  getBlocks,
  listAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  cloneAgent,
  setAgentVisibility,
  activateVersion as apiActivateVersion,
  revertVersion as apiRevertVersion,
  forkVersion as apiForkVersion,
  exposeAgent,
  connectAgent as apiConnectAgent,
  resyncAgent,
  refreshAgentPrompt,
  listModels,
  listCollections,
  type Model,
  type Collection,
} from '../../../api'
import type { Agent, AgentConfig, BlockCategory } from '../../mockData'

export interface UseAgents {
  agents: Agent[]
  blocks: Record<string, BlockCategory>
  models: Model[]
  collections: Collection[]
  create: (name: string, config: AgentConfig, description: string | null) => Promise<Agent>
  update: (id: string, name: string, config: AgentConfig, description: string) => Promise<Agent>
  remove: (id: string) => Promise<void>
  clone: (id: string) => Promise<Agent>
  connect: (url: string, token?: string) => Promise<Agent>
  setVisibility: (id: string, pub: boolean) => Promise<Agent>
  expose: (id: string, on: boolean) => Promise<Agent>
  activate: (id: string, version: string) => Promise<Agent>
  fork: (id: string) => Promise<Agent>
  revert: (id: string, version: string) => Promise<Agent>
  resync: (id: string) => Promise<Agent>
  refreshPrompt: (id: string) => Promise<Agent>
}

export function useAgents(): UseAgents {
  const [agents, setAgents] = useState<Agent[]>([])
  // 초기 목록: setAgents 직접(notify 안 쏨 — 재페치 루프 방지). useAsyncData 불가(로컬 뮤테이션).
  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch((e) => message.error(String(e)))
  }, [])
  // 레퍼런스 데이터(마운트 후 불변) — useAsyncData로 흡수.
  const { data: blocks = {} } = useAsyncData(getBlocks, [])
  const { data: models = [] } = useAsyncData(() => listModels('chat'), [])
  const { data: collections = [] } = useAsyncData(listCollections, [])

  // 단일 에이전트 교체 + 탭 간 변경 신호(스펙 080). 초기 로드는 이 경로를 안 타 신호가 안 나간다.
  const replace = (updated: Agent): Agent => {
    setAgents((as) => as.map((a) => (a.id === updated.id ? updated : a)))
    notifyAgentsChanged()
    return updated
  }
  const prepend = (created: Agent): Agent => {
    setAgents((as) => [created, ...as])
    notifyAgentsChanged()
    return created
  }

  return {
    agents,
    blocks,
    models,
    collections,
    create: async (name, config, description) => prepend(await createAgent(name, config, description)),
    update: async (id, name, config, description) => replace(await updateAgent(id, name, config, description)),
    remove: async (id) => {
      await deleteAgent(id)
      setAgents((as) => as.filter((a) => a.id !== id))
      notifyAgentsChanged()
    },
    clone: async (id) => prepend(await cloneAgent(id)),
    connect: async (url, token) => prepend(await apiConnectAgent(url, token)),
    setVisibility: async (id, pub) => replace(await setAgentVisibility(id, pub)),
    expose: async (id, on) => replace(await exposeAgent(id, on)),
    activate: async (id, version) => replace(await apiActivateVersion(id, version)),
    fork: async (id) => replace(await apiForkVersion(id)),
    revert: async (id, version) => replace(await apiRevertVersion(id, version)),
    resync: async (id) => replace(await resyncAgent(id)),
    refreshPrompt: async (id) => replace(await refreshAgentPrompt(id)),
  }
}
