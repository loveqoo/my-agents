/* 공용 모델 컨트롤(스펙 274) — 에이전트 폼·노드 카드·오버라이드 드로어가 **같은** 모델 Select를
   조립한다(MemoryFields 271 패턴). chat 필터·미등록 값 보존을 여기 한 곳에(drift 0):
   - chat 필터: embedding 모델은 대화 불가 — 옵션에서 제외(274 이전 에이전트 폼만 무필터 버그,
     저장은 통과하나 런타임 해석이 kind=="chat" 조회라 대화 시점에 실패).
   - 미등록 값 보존: 현재 값이 목록에 없으면(구 저장·미등록·이미 저장된 embedding) 옵션에 보존해
     편집 시 선택이 사라지지 않게 — 값 교정은 사용자가, UI는 은닉하지 않는다. */
import { Select } from 'antd'
import type { ReactNode } from 'react'

const HELP = { fontSize: 12, color: 'var(--color-text-tertiary)' } as const
const LABEL = { fontSize: 13, color: 'var(--color-text)', fontWeight: 500 } as const

type ModelLike = { name: string; kind: string }

/** 등록 chat 모델 → Select 옵션(단일 출처). 새 노드 기본값 등 옵션 밖 소비도 이걸 쓴다. */
export const chatModelOptions = (models: ModelLike[]) =>
  models.filter((m) => m.kind === 'chat').map((m) => ({ label: m.name, value: m.name }))

export function ModelField({
  value,
  onChange,
  models,
  placeholder,
  required = false,
  hint,
}: {
  value: string
  onChange: (v: string) => void
  models: ModelLike[]
  placeholder?: string
  required?: boolean // 노드=true(비면 error status)
  hint?: ReactNode // 표면별 보조 문구(오버라이드 mock-llm 안내 등)
}) {
  const options = chatModelOptions(models)
  if (value && !options.some((o) => o.value === value)) {
    options.push({ label: value, value })
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={LABEL}>모델</span>
      <Select
        value={value || undefined}
        onChange={onChange}
        options={options}
        placeholder={placeholder}
        status={required && !value.trim() ? 'error' : undefined}
        style={{ width: '100%' }}
      />
      {typeof hint === 'string' ? <span style={HELP}>{hint}</span> : hint}
    </div>
  )
}
