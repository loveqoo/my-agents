/* PickerGroups (스펙 109) — 늘어나는 항목을 효율적으로 고르는 재사용 피커.
   종류별 접이식(antd Collapse) + 헤더 `선택/전체` 카운트 + 항목 많으면(>threshold) 패널 내 검색 +
   선택 있는 그룹 기본 펼침. 등록 폼(AgentsView)·플레이그라운드 오버라이드(OverridePanel) 공용 →
   렌더·검색·카운트 로직 drift 0. 항목이 100개여도 접힌 헤더+검색으로 폼 높이가 안 늘어난다(스펙 107). */
import { useState } from 'react'
import { Collapse, Checkbox, Input, Tag } from 'antd'

export type PickerItem = {
  id: string
  label: string
  hint?: string // 회색 보조 설명줄(메모리 설명·컬렉션 임베딩 등)
  extra?: React.ReactNode // 라벨 뒤 노드(권한 승인자 태그 등)
}
export type PickerGroup = {
  key: string
  title: string
  items: PickerItem[]
  emptyText?: string // 항목 0일 때 안내(없으면 "없음")
}

export function PickerGroups({
  groups,
  selected,
  onToggle,
  searchThreshold = 6,
}: {
  groups: PickerGroup[]
  selected: string[]
  onToggle: (id: string) => void
  searchThreshold?: number
}) {
  const [search, setSearch] = useState<Record<string, string>>({})
  const sel = new Set(selected)

  return (
    <Collapse
      size="small"
      defaultActiveKey={groups.filter((g) => g.items.some((it) => sel.has(it.id))).map((g) => g.key)}
      items={groups.map((g) => {
        const chosen = g.items.filter((it) => sel.has(it.id)).length
        const q = (search[g.key] ?? '').trim().toLowerCase()
        const shown = q
          ? g.items.filter((it) => (it.label + ' ' + (it.hint ?? '')).toLowerCase().includes(q))
          : g.items
        return {
          key: g.key,
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              {g.title}
              <Tag color={chosen > 0 ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
                {chosen}/{g.items.length}
              </Tag>
            </span>
          ),
          children:
            g.items.length === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>
                {g.emptyText ?? '없음'}
              </span>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {g.items.length > searchThreshold && (
                  <Input
                    allowClear
                    size="small"
                    placeholder={`${g.title} 검색...`}
                    value={search[g.key] ?? ''}
                    onChange={(e) => setSearch((s) => ({ ...s, [g.key]: e.target.value }))}
                  />
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {shown.map((it) => (
                    <Checkbox
                      key={it.id}
                      checked={sel.has(it.id)}
                      onChange={() => onToggle(it.id)}
                      style={{ alignItems: 'flex-start', marginInlineStart: 0 }}
                    >
                      <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                          {it.label}
                          {it.extra}
                        </span>
                        {it.hint ? (
                          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{it.hint}</span>
                        ) : null}
                      </span>
                    </Checkbox>
                  ))}
                  {shown.length === 0 && (
                    <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>검색 결과 없음</span>
                  )}
                </div>
              </div>
            ),
        }
      })}
    />
  )
}
