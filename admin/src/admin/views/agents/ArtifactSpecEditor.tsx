import { Input, Select, Button, Switch } from 'antd'
import type { ArtifactSpec, ArtifactField } from '../../mockData'

/* 노코드 산출물형 필드 편집기(스펙 190) — impl=artifact_form일 때 "하는 일" 자리에 뜬다.
   내부어(produce·프리미티브 등) 미노출, 일상어로: 모을 항목 + 선택지/자유입력 + 결과 보낼 곳(고정 문구).
   결과 키(JSON 키)는 호스트 콜백이 받는 이름이라 노출하되 기본값(field1..)을 제공한다. */
export function ArtifactSpecEditor({
  value,
  onChange,
}: {
  value: ArtifactSpec | undefined
  onChange: (spec: ArtifactSpec) => void
}) {
  const fields = value?.fields ?? []
  const update = (next: ArtifactField[]) => onChange({ kind: value?.kind, fields: next })
  const setField = (i: number, patch: Partial<ArtifactField>) =>
    update(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const add = () => update([...fields, { key: `field${fields.length + 1}`, label: '', required: true }])
  const remove = (i: number) => update(fields.filter((_, j) => j !== i))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        모을 항목을 정의합니다. 선택지를 넣으면 사용자에게 고르게 하고, 비우면 자유롭게 답하게 합니다.
        완성된 결과(JSON)는 임베드한 페이지의 JS 콜백으로 전달됩니다.
      </span>
      {fields.length === 0 && (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>
          아직 항목이 없습니다 — 아래 "항목 추가"로 시작하세요.
        </span>
      )}
      {fields.map((f, i) => {
        const isChoice = Array.isArray(f.candidates)
        return (
          <div
            key={i}
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              padding: 12,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', gap: 8 }}>
              <Input
                placeholder="항목 이름 (예: 구매이력)"
                value={f.label}
                onChange={(e) => setField(i, { label: e.target.value })}
              />
              <Input
                placeholder="결과 키"
                style={{ width: 140 }}
                value={f.key}
                onChange={(e) => setField(i, { key: e.target.value })}
              />
              <Button danger type="text" onClick={() => remove(i)}>
                삭제
              </Button>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Select
                size="small"
                style={{ width: 150 }}
                value={isChoice ? 'choice' : 'free'}
                onChange={(v) => setField(i, { candidates: v === 'choice' ? f.candidates ?? [] : undefined })}
                options={[
                  { value: 'free', label: '자유 입력' },
                  { value: 'choice', label: '선택지 중 고르기' },
                ]}
              />
              {isChoice && (
                <Select
                  mode="tags"
                  size="small"
                  style={{ flex: 1, minWidth: 200 }}
                  placeholder="선택지 입력 후 Enter (예: 최근, 7일 전, 최근 한 달)"
                  value={f.candidates}
                  onChange={(vals) => setField(i, { candidates: vals })}
                  options={[]}
                />
              )}
              <span style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Switch size="small" checked={f.required !== false} onChange={(c) => setField(i, { required: c })} />
                필수
              </span>
            </div>
          </div>
        )
      })}
      <Button onClick={add} style={{ alignSelf: 'flex-start' }}>
        + 항목 추가
      </Button>
    </div>
  )
}

/* 저장 가능한 최소 조건(스펙 190) — 유효 필드(이름+키 채움) ≥1. 폼 okButton이 이걸로 게이트. */
export function artifactSpecValid(spec: ArtifactSpec | undefined): boolean {
  return !!spec?.fields?.some((f) => f.key.trim() && f.label.trim())
}
