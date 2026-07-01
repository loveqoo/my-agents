/* my-agents admin — 메모리 회상 시험 드로어 (스펙 084·097).
   에이전트/유저 메모리 패널이 공유한다 — 챗과 *같은 코어*(memory.search)로 스코프에 질의해
   "이 쿼리로 무엇이 회상되는가"를 즉석 확인. 공유 RetrievalTestDrawer(097)의 메모리 어댑터 —
   컬렉션 SearchDrawer와 셸을 공유해 UI drift 0. onSearch만 주입(searchAgentMemory/searchUserMemory 바인딩).
   enabled=false(미구성) vs 0건 회상(enabled=true·빈 results) 구분은 공유 셸이 disabledAlert로 처리(None≠[]). */
import { Alert, Tag } from 'antd'
import { RetrievalTestDrawer } from './RetrievalTestDrawer'
import { type MemorySearchOut, type MemoryHit } from '../../api'

export function RecallDrawer({
  open,
  title,
  scopeKey,
  onClose,
  onSearch,
}: {
  open: boolean
  title: string
  scopeKey: string // 스코프(에이전트/유저) 식별자 — 바뀌면 질의·결과 초기화
  onClose: () => void
  onSearch: (query: string, limit: number) => Promise<MemorySearchOut>
}) {
  return (
    <RetrievalTestDrawer<MemoryHit>
      open={open}
      title={title}
      scopeKey={scopeKey}
      onClose={onClose}
      onSearch={async (q, l) => {
        const out = await onSearch(q, l)
        return { results: out.results, enabled: out.enabled }
      }}
      hint={
        <>
          에이전트가 채팅에서 회상하는 것과 <b>같은 메모리 코어</b>로 이 스코프에 질의합니다. 관련도(1.0=가장
          관련) 내림차순 상위 기억을 보여줍니다 — 저장된 기억이 의도대로 회상되는지 즉석 확인하세요.
        </>
      }
      disabledAlert={
        <Alert
          type="info"
          showIcon
          title="장기 기억이 비활성/미구성입니다"
          description="이 스코프는 장기 기억(mem0)이 설정되지 않아 회상할 수 없습니다. 임베딩 모델·에이전트 메모리 설정을 확인하세요."
        />
      }
      queryPlaceholder="예: 내가 선호하는 보고서 형식은?"
      limitLabel="limit (1–10)"
      runLabel="조회"
      scoreLabel="관련도"
      countLabel={(n) => `회상 ${n}건`}
      emptyMessage="회상된 기억이 없습니다."
      emptyQueryWarn="질의를 입력하세요"
      noResultInfo="회상된 기억이 없습니다"
      errorFallback="조회에 실패했습니다"
      renderMeta={(h) => (
        <>
          <Tag>{h.scope}</Tag>
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{h.type}</span>
        </>
      )}
    />
  )
}
