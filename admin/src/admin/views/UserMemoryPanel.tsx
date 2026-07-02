/* my-agents admin — 유저 메모리(user_id) 큐레이션 패널 (스펙 030·127).
   유저가 대화 중 남긴 장기 기억을 **한 검색 표면**에서 다룬다(127): [일치 | 유사도] 모드 전환 —
   일치=서버 페이지네이션 부분일치 목록(증가해도 가벼움, 행에서 수정·삭제), 유사도=회상 시험(RecallPanel,
   관련도+진단). 관리자는 유저 사실을 *저작*하지 않고 *교정*만 한다 → add 없음. */
import { useState } from 'react'
import { Segmented } from 'antd'
import {
  pageUserMemory,
  updateUserMemory,
  deleteUserMemory,
  searchUserMemory,
} from '../../api'
import { PagedMemoryList } from './PagedMemoryList'
import { RecallPanel } from './RecallPanel'

export function UserMemoryPanel({ userId, label }: { userId: string; label?: string }) {
  const [mode, setMode] = useState<'exact' | 'similar'>('exact')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Segmented
          value={mode}
          onChange={(v) => setMode(v as 'exact' | 'similar')}
          options={[
            { label: '일치 검색', value: 'exact' },
            { label: '유사도 검색', value: 'similar' },
          ]}
        />
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          이 유저가 대화 중 남긴 장기 기억. <b>{label ?? userId}</b>에게만 회상됩니다 — 잘못되거나 민감한
          정보는 여기서 교정·삭제하세요.
        </span>
      </div>

      {mode === 'exact' ? (
        <PagedMemoryList
          scopeKey={userId}
          scopeLabel={userId}
          fetchPage={(q, l, o) => pageUserMemory(userId, q, l, o)}
          onEdit={async (memId, text) => {
            await updateUserMemory(userId, memId, text)
          }}
          onDelete={async (memId) => {
            await deleteUserMemory(userId, memId)
          }}
        />
      ) : (
        <RecallPanel scopeKey={userId} onSearch={(q, l) => searchUserMemory(userId, q, l)} />
      )}
    </div>
  )
}
