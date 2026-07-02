/* my-agents admin — 메모리 회상 시험 패널 (스펙 084·097·125·126).
   에이전트/유저 메모리 상세 페이지가 공유한다 — 챗과 *같은 코어*(memory.search)로 스코프에 질의해
   "이 쿼리로 무엇이 회상되는가"를 즉석 확인. 126에서 드로어를 벗고 **상세 페이지 상단 인라인**으로
   넓게 쓴다(컬렉션 SearchDrawer는 여전히 드로어). 공유 RetrievalTestPanel의 메모리 어댑터 — onSearch만
   주입(searchAgentMemory/searchUserMemory 바인딩). enabled=false(미구성) vs 0건 회상 구분·진단(diag)은
   패널이 처리(None≠[], 스펙 125). */
import { Alert, Tag } from 'antd'
import { RetrievalTestPanel } from './RetrievalTestPanel'
import { type MemorySearchOut, type MemoryHit } from '../../api'

export function RecallPanel({
  scopeKey,
  onSearch,
}: {
  scopeKey: string // 스코프(에이전트/유저) 식별자 — 바뀌면 질의·결과 초기화
  onSearch: (query: string, limit: number) => Promise<MemorySearchOut>
}) {
  return (
    <RetrievalTestPanel<MemoryHit>
      scopeKey={scopeKey}
      onSearch={async (q, l) => {
        const out = await onSearch(q, l)
        return { results: out.results, enabled: out.enabled, diag: out.diag } // 진단 통과(스펙 125)
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
