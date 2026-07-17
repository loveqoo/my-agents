/* 공용 기억 컨트롤(스펙 271, 3부작 3/3) — 에이전트 폼과 노드 카드가 **같은** 단기/장기 기억 컨트롤을
   조립한다. 라벨·옵션·도움말을 여기 한 곳에 정의(drift 0). 269·270이 심은 단기/장기 대칭의 UI 실현.

   - 단기 기억 = historyDepth(이전 대화 N개). 에이전트=루트(상속 없음)·노드=상속 가능(allowInherit).
   - 장기 기억 = mem0 회상 블록(269 이후 단일 옵션). 노드는 회상 키워드(memoryQuery)까지, 에이전트는
     비영속 게이트(ephemeral)까지 — 성격차는 prop으로 흡수하되 라벨·옵션은 공유.
   밀도(variant): 밀도만 다르고 의미는 동일(안 B — facet별 공용 컨트롤). */
import { Checkbox, Select, Segmented } from 'antd'

const HELP = { fontSize: 12, color: 'var(--color-text-tertiary)' } as const
const LABEL = { fontSize: 13, color: 'var(--color-text)', fontWeight: 500 } as const

// 단기 기억 옵션(공유) — 0=대화를 넣지 않음, N=최근 N개 메시지. 라벨 한 곳.
const DEPTH_OPTS = [
  { label: '기억 안 함 (0개)', value: 0 },
  { label: '최근 6개 메시지', value: 6 },
  { label: '최근 10개 메시지', value: 10 },
  { label: '최근 20개 메시지', value: 20 },
  { label: '최근 40개 메시지', value: 40 },
  { label: '최근 100개 메시지', value: 100 },
]
const INHERIT = { label: '상속 (에이전트 설정)', value: 'inherit' }

export function ShortTermMemoryField({
  value,
  onChange,
  allowInherit = false,
  disabled = false,
  hint,
}: {
  value: number | null | undefined
  onChange: (v: number | null) => void
  allowInherit?: boolean // 노드=true(미지정→상속), 에이전트=false(루트)
  disabled?: boolean // 노드 clean일 때 비활성(대화 안 봄)
  hint?: string // 밀도별 도움말(없으면 기본)
}) {
  const opts = allowInherit ? [INHERIT, ...DEPTH_OPTS] : DEPTH_OPTS
  const sel = allowInherit ? (value == null ? 'inherit' : value) : (value ?? 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={LABEL}>단기 기억</span>
      <Select
        value={sel}
        onChange={(v) => onChange(v === 'inherit' ? null : (v as number))}
        disabled={disabled}
        style={{ width: '100%' }}
        options={opts}
      />
      <span style={HELP}>{hint ?? '이 노드가 볼 이전 대화 턴 수(상속=에이전트 설정).'}</span>
    </div>
  )
}

export function LongTermMemoryField({
  value,
  onChange,
  options,
  ephemeral = false,
  queryMode,
  onQueryModeChange,
}: {
  value: string[]
  onChange: (v: string[]) => void
  options: { label: string; value: string }[]
  ephemeral?: boolean // 에이전트 비영속=회상 안 함(비활성)
  queryMode?: 'user' | 'input' // 노드만 — 회상 키워드 기준(주면 노출)
  onQueryModeChange?: (v: 'user' | 'input') => void
}) {
  const noOpts = options.length === 0
  // 비영속 미선택-잠금(에이전트, codex 238 #1): 새 선택만 막고(옵션별 disabled) 기선택은 해제 가능 —
  // "선택했는데 무동작" 함정과 "해제 불가" 모순을 동시에 피한다. 노드는 ephemeral 없음(무영향).
  const effOptions = ephemeral ? options.map((o) => ({ ...o, disabled: !value.includes(o.value) })) : options
  // 단일 블록이면 체크박스(스펙 387 후속, 구남님 제안) — 실동작 기억 블록이 "장기 기억 (mem0)"
  // 하나뿐이라 다중 선택은 과함. 블록이 늘면(어드민 CRUD) 기존 다중 Select로 자동 복귀.
  const single = options.length === 1 ? options[0] : null
  const singleChecked = single !== null && value.includes(single.value)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={LABEL}>장기 기억</span>
      {single ? (
        <Checkbox
          checked={singleChecked}
          // 비영속 미선택-잠금 미러: 새로 켜기는 막고, 켜져 있던 건 끌 수 있다.
          disabled={ephemeral && !singleChecked}
          onChange={(e) => onChange(e.target.checked ? [single.value] : [])}
        >
          {single.label} 사용
        </Checkbox>
      ) : (
        <Select
          mode="multiple"
          allowClear
          value={value}
          onChange={onChange}
          options={effOptions}
          disabled={noOpts}
          placeholder={noOpts ? '등록된 기억 없음' : ephemeral ? '비영속(1회성)은 기억을 쓰지 않습니다' : 'mem0 장기 기억에서 회상'}
          style={{ width: '100%' }}
        />
      )}
      {ephemeral ? (
        <span style={HELP}>비영속(1회성) 에이전트는 기억을 회상·저장하지 않습니다.</span>
      ) : queryMode !== undefined && value.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 2 }}>
          <span style={LABEL}>기억 찾는 기준</span>
          <Segmented
            value={queryMode}
            onChange={(v) => onQueryModeChange?.(v as 'user' | 'input')}
            options={[
              { label: '사용자 질문으로', value: 'user' },
              { label: '앞 단계 결과로', value: 'input' },
            ]}
          />
        </div>
      ) : (
        <span style={HELP}>
          켜면 대화에서 사실을 추출·저장하고 관련 기억을 회상합니다. 로그인 사용자와의 대화는 유저
          단위로 세션을 넘어 기억합니다. 머신/A2A 호출은 userId를 함께 보내면 그 유저 단위로 똑같이
          기억하고, 없으면 이번 대화에만 유지합니다.
        </span>
      )}
    </div>
  )
}
