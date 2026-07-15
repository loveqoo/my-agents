/* 공용 프롬프트 컨트롤(스펙 274) — **텍스트 작성(사본) 표면** 전용: 노드 카드·오버라이드 드로어.
   라벨 줄에 "등록 프롬프트에서 가져오기" 콤팩트 로더(learning 078: 세로 스택·형제 폭 다툼 금지),
   블록을 고르면 body가 TextArea에 복사되고 이후 자유편집. 에이전트 폼의 프롬프트는 **참조 저장**
   (블록 이름을 저장, 런타임 해석)이라 시맨틱이 달라 여기 안 태운다(247 "같은 개념≠같은 컴포넌트"). */
import { Select, Input } from 'antd'

const HELP = { fontSize: 12, color: 'var(--color-text-tertiary)' } as const
const LABEL = { fontSize: 13, color: 'var(--color-text)', fontWeight: 500 } as const

export function PromptField({
  label,
  value,
  onChange,
  prompts,
  placeholder,
  required = false,
  hint,
}: {
  label: string // 노드='프롬프트', 오버라이드='시스템 프롬프트'
  value: string
  onChange: (v: string) => void
  prompts: { name: string; body: string }[]
  placeholder?: string
  required?: boolean // 노드=true(비면 error status)
  hint?: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={LABEL}>{label}</span>
        {prompts.length > 0 && (
          <Select
            size="small"
            style={{ width: 200 }}
            value={undefined}
            placeholder="등록 프롬프트에서 가져오기"
            options={prompts.map((p) => ({ label: p.name, value: p.name }))}
            onChange={(name) => {
              const p = prompts.find((x) => x.name === name)
              if (p) onChange(p.body)
            }}
          />
        )}
      </div>
      <Input.TextArea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoSize={{ minRows: 3, maxRows: 10 }}
        placeholder={placeholder}
        status={required && !value.trim() ? 'error' : undefined}
      />
      {hint ? <span style={HELP}>{hint}</span> : null}
    </div>
  )
}
