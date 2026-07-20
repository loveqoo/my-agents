/* 능력→설정 오버라이드 단일 컴포넌트(스펙 409·411·412). 에이전트 폼·플레이그라운드 오버라이드·노드
   편집기가 **공유**한다(사본 금지 — 회고 261 "사본이면 드리프트"의 설정 축 교정). 서술자 목록
   (백엔드 정본)으로 렌더하므로 설정이 늘면 이 컴포넌트를 안 고쳐도 자동 반영된다.

   스펙 411: params는 kind별로 다른 표현이다 — bool은 상속(키 없음)/켬/끔 3상, number는
   상속(미설정)/값(min~max, step, isInt면 정수)이다. 능력이 아니라 **사용값**을 덮는다 — 모델이
   못 하는 걸 켤 수는 없어(부분집합 불가침), 능력 false인 bool 축은 '켬'을 비활성하고 사유를 표시한다.
   temperature도 이제 params 안 kind=number 항목이라(스펙 077 TemperatureField 은퇴) 이 컴포넌트가 담는다.

   스펙 412: 능력(서버가 할 수 있는 사실)과 파라미터(요청마다 조정하는 값)를 **다른 시각언어**로
   분리한다(외부 사례 조사 결론). 이 파일은 파라미터 오버라이드 쪽 — 능력 선언은 ProviderModelView의
   CapsEditor가 별 블록으로 담당한다. 여기서는 두 공유 조각을 내보낸다:
   - ParamNumberField: Slider(대략)+InputNumber(정밀) 동기화 — 모델 폼·오버라이드 양쪽이 재사용.
   - PARAM_PRESETS: temperature·top_p 프리셋(정밀/균형/창의) — 매 파라미터를 낱개로 만지지 않고
     흔한 조합을 한 번에 고르게(직접=프리셋 미적용). */
import { Button, Collapse, Flex, InputNumber, Segmented, Select, Slider, Tag, Tooltip, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { getCapabilityDescriptors, type ModelDescriptors, type ParamDescriptor } from '../../../api'

const { Text } = Typography

const EMPTY_DESCRIPTORS: ModelDescriptors = { capabilities: [], params: [] }

// 서술자는 사실상 정적(백엔드 상수) — 프로세스 1회 fetch 후 캐시(프롭 배관 없이 어느 소비처든 훅 호출).
let _cache: ModelDescriptors | null = null
let _inflight: Promise<ModelDescriptors> | null = null

export function useCapabilityDescriptors(): ModelDescriptors {
  const [d, setD] = useState<ModelDescriptors>(_cache ?? EMPTY_DESCRIPTORS)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (_cache) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    if (!_inflight) _inflight = getCapabilityDescriptors().then((r) => (_cache = r))
    _inflight
      .then((r) => alive && setD(r))
      .catch(() => {
        // 실패 시 _inflight를 비우고 **현재 마운트에서도** 백오프 재시도(codex 재검 P2① — _inflight만
        // 비우면 재마운트해야 재시도라 화면이 계속 떠 있으면 빈 UI 고착). 최대 5회, 성공 값만 캐시.
        _inflight = null
        if (alive && attempt < 5) timer = setTimeout(() => setAttempt((a) => a + 1), 1000 * (attempt + 1))
      })
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [attempt])
  return d
}

/** 파라미터 프리셋(스펙 412) — temperature·top_p만 대상. '직접'은 이 목록에 없다(프리셋 미적용 상태). */
export const PARAM_PRESETS: Record<string, { temperature: number; top_p: number }> = {
  정밀: { temperature: 0.2, top_p: 0.9 },
  균형: { temperature: 0.7, top_p: 1.0 },
  창의: { temperature: 1.2, top_p: 1.0 },
}

/** number 파라미터 공용 필드 — Slider(대략)+InputNumber(정밀)를 같은 값에 동기화한다.
 *  모델 폼(ProviderModelView CapsEditor)과 오버라이드(CapabilitySettings) 양쪽이 재사용(사본 금지). */
export function ParamNumberField({
  label,
  min,
  max,
  step,
  isInt,
  value,
  onChange,
  placeholder,
  disabled,
  reason,
  size = 'small',
}: {
  label: string
  min?: number | null
  max?: number | null
  step?: number | null
  isInt?: boolean
  value: number | undefined
  onChange: (v: number | undefined) => void
  placeholder?: string
  disabled?: boolean
  reason?: string
  size?: 'small' | 'middle'
}) {
  const sliderMin = min ?? 0
  const sliderMax = max ?? 1
  const field = (
    <Flex vertical gap={2} style={{ width: '100%' }}>
      <Text style={{ fontSize: 13, fontWeight: 600 }}>{label}</Text>
      <Flex align="center" gap={8}>
        <Slider
          style={{ flex: 1, minWidth: 100 }}
          min={sliderMin}
          max={sliderMax}
          step={step ?? (isInt ? 1 : 0.1)}
          value={value ?? sliderMin}
          disabled={disabled}
          onChange={(v) => onChange(v)}
        />
        <InputNumber
          size={size}
          style={{ width: 100 }}
          min={min ?? undefined}
          max={max ?? undefined}
          step={step ?? undefined}
          precision={isInt ? 0 : undefined}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(v) => onChange(v == null ? undefined : v)}
        />
      </Flex>
    </Flex>
  )
  // disabled 요소는 pointer-events가 막혀 Tooltip hover가 안 걸린다 — span 래퍼로 hover 표면 확보.
  if (disabled && reason) {
    return (
      <Tooltip title={reason}>
        <span style={{ display: 'block' }}>{field}</span>
      </Tooltip>
    )
  }
  return field
}

type ModelParams = Record<string, boolean | number | undefined>

/** 이 층에서 상속했을 때 실제로 켜질지(bool 전용, 모델 params → 서술자 default, 능력 false면 무조건 끔).
 *  BE resolve_effective와 **일치**(codex 재검 P2②): 모델 params 값이 진짜 bool일 때만 그 값을
 *  쓰고, 비-bool(문자열 "false" 등)은 서술자 default로 폴백(FE가 켬으로 오표시하던 것 봉인). */
function inheritedOn(p: ParamDescriptor, capable: boolean, modelDefaults?: Record<string, unknown>): boolean {
  if (!capable) return false
  const v = modelDefaults?.[p.key]
  return typeof v === 'boolean' ? v : Boolean(p.default)
}

/** 상속 시 표시할 모델 기본값(number 전용) — modelDefaults가 진짜 number면 그 값, 아니면 서술자 default. */
function inheritedNumber(p: ParamDescriptor, modelDefaults?: Record<string, unknown>): number {
  const v = modelDefaults?.[p.key]
  return typeof v === 'number' ? v : Number(p.default)
}

/** 현재 value가 어느 프리셋과 일치하는지(temperature·top_p 둘 다 정확히 일치해야) — 아니면 '직접'. */
function matchPreset(value: ModelParams): string {
  for (const name of Object.keys(PARAM_PRESETS)) {
    const preset = PARAM_PRESETS[name]
    if (value.temperature === preset.temperature && value.top_p === preset.top_p) return name
  }
  return '직접'
}

export function CapabilitySettings({
  descriptors,
  capabilities,
  value,
  onChange,
  modelDefaults,
  size = 'small',
}: {
  descriptors: ModelDescriptors
  capabilities: Record<string, boolean> | undefined
  value: ModelParams
  onChange: (next: ModelParams) => void
  modelDefaults?: Record<string, unknown> // 선택 모델의 params(상속 값 표시용)
  size?: 'small' | 'middle'
}) {
  const { params } = descriptors
  if (!params.length) return null

  // 능력 판정은 백엔드 resolve_effective와 **일치**(codex P2②): 키가 진짜 bool이면 그 값,
  // 아니면(누락·비-bool) 서술자 capDefault(descriptors.capabilities에서 조회). cap=null이면
  // 능력 게이트 없음(항상 가능) — capabilities=undefined(미조회)면 낙관적 허용.
  const capableFor = (p: ParamDescriptor): boolean => {
    if (!p.cap) return true
    const fact = descriptors.capabilities.find((c) => c.cap === p.cap)
    const raw = capabilities?.[p.cap]
    return capabilities ? (typeof raw === 'boolean' ? raw : (fact?.capDefault ?? true)) : true
  }

  const renderParam = (p: ParamDescriptor) => {
    const capable = capableFor(p)
    const reason = !capable ? `이 서버는 ${p.label}을(를) 지원하지 않습니다` : undefined

    if (p.kind === 'bool') {
      const cur = value[p.key] === undefined ? 'inherit' : value[p.key] ? 'on' : 'off'
      const inh = inheritedOn(p, capable, modelDefaults)
      const field = (
        <Flex vertical gap={2} key={p.key}>
          <Text style={{ fontSize: 13, fontWeight: 600 }}>{p.label}</Text>
          <Select
            size={size}
            style={{ width: 220 }}
            value={cur}
            onChange={(v) => {
              const mp = { ...value }
              if (v === 'inherit') delete mp[p.key]
              else mp[p.key] = v === 'on'
              onChange(mp)
            }}
            options={[
              { value: 'inherit', label: `모델 기본(상속 — ${inh ? '켬' : '끔'})` },
              { value: 'on', label: '켬', disabled: !capable },
              { value: 'off', label: '끔' },
            ]}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {capable
              ? `모델 기본값을 이 층에서 덮습니다(상속=모델 설정 따름).`
              : `이 모델은 ${p.label}을(를) 지원하지 않아 켤 수 없습니다(능력 우선).`}
          </Text>
        </Flex>
      )
      if (!capable && reason) {
        return (
          <Tooltip key={p.key} title={reason}>
            <span style={{ display: 'block' }}>{field}</span>
          </Tooltip>
        )
      }
      return field
    }

    // number: 상속(미설정)/값(min~max, step, isInt면 정수).
    const cur = value[p.key]
    const curNum = typeof cur === 'number' ? cur : undefined
    const inh = inheritedNumber(p, modelDefaults)
    return (
      <Flex align="center" gap={8} key={p.key}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ParamNumberField
            label={p.label}
            min={p.min}
            max={p.max}
            step={p.step}
            isInt={p.isInt}
            value={curNum}
            onChange={(v) => {
              const mp = { ...value }
              if (v === undefined) delete mp[p.key]
              else mp[p.key] = v
              onChange(mp)
            }}
            placeholder={`모델 기본 ${inh}`}
            disabled={!capable}
            reason={reason}
            size={size}
          />
        </div>
        {curNum !== undefined ? (
          <Flex vertical gap={2} align="flex-end">
            <Tag color="blue">오버라이드</Tag>
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: 'auto' }}
              onClick={() => {
                const mp = { ...value }
                delete mp[p.key]
                onChange(mp)
              }}
            >
              기본으로 되돌리기
            </Button>
          </Flex>
        ) : null}
      </Flex>
    )
  }

  const basicParams = params.filter((p) => !p.advanced)
  const advancedParams = params.filter((p) => p.advanced)
  const hasPresetParams = params.some((p) => p.key === 'temperature') && params.some((p) => p.key === 'top_p')

  return (
    <Flex vertical gap={12}>
      {hasPresetParams ? (
        <Flex vertical gap={2}>
          <Text style={{ fontSize: 13, fontWeight: 600 }}>프리셋</Text>
          <Segmented
            size={size}
            value={matchPreset(value)}
            onChange={(v) => {
              const name = String(v)
              if (name === '직접') {
                const mp = { ...value }
                delete mp.temperature
                delete mp.top_p
                onChange(mp)
                return
              }
              onChange({ ...value, ...PARAM_PRESETS[name] })
            }}
            options={[...Object.keys(PARAM_PRESETS), '직접'].map((n) => ({ label: n, value: n }))}
          />
        </Flex>
      ) : null}
      {basicParams.map((p) => renderParam(p))}
      {advancedParams.length ? (
        <Collapse
          ghost
          size={size}
          items={[
            {
              key: 'advanced',
              label: '고급',
              children: (
                <Flex vertical gap={12}>
                  {advancedParams.map((p) => renderParam(p))}
                </Flex>
              ),
            },
          ]}
        />
      ) : null}
      {/* 안내(스펙 410) — 사고 과정은 모델 서버가 reasoning 파서를 지원할 때 스트리밍으로 표시된다
          (예: rapid-mlx `--reasoning-parser qwen3`, vLLM `--reasoning-parser`). thinking 설정이 있을 때만 노출. */}
      {params.some((p) => p.cap === 'thinking') ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          Thinking을 켜면 모델의 사고 과정이 대화에 접이식 패널로 표시됩니다(서버가 reasoning 파서를 지원할 때).
        </Text>
      ) : null}
    </Flex>
  )
}
