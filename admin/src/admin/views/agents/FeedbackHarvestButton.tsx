import { useEffect, useState } from 'react'
import { Button, Badge, Tooltip, message } from 'antd'
import { Icon } from '../../icons'
import { getHarvestCount, harvestFeedback } from '../../../api'

/**
 * 피드백 수확 버튼 (스펙 209 Phase 2) — 이 에이전트의 미수확 응답 피드백(👍/👎)을 초안 평가
 * 케이스로 수확. 에이전트 소유자/admin만(can_manage) 렌더. 수확은 배경 작업 → "평가"에서 검토·활성화.
 * 자기완결: 열릴 때 미수확 수 조회, 클릭 시 수확 트리거 후 재조회. antd Button+Badge 조립.
 */
export function FeedbackHarvestButton({ agentId }: { agentId: string }) {
  const [count, setCount] = useState<number | null>(null)
  const [hasDataset, setHasDataset] = useState(false)
  const [busy, setBusy] = useState(false)

  const refresh = () => {
    getHarvestCount(agentId)
      .then((r) => {
        setCount(r.available)
        setHasDataset(r.dataset_id != null)
      })
      .catch(() => setCount(null)) // 조회 실패(권한 등)=조용히 숨김
  }
  useEffect(refresh, [agentId])

  const onHarvest = async () => {
    setBusy(true)
    try {
      const ds = await harvestFeedback(agentId)
      message.success(`피드백 수확 시작 — "${ds.name}" 초안을 평가에서 검토하세요`)
      refresh()
    } catch {
      message.error('수확에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  if (count === null) return null // 미조회/권한없음
  const nothing = count === 0 && !hasDataset

  return (
    <Tooltip
      title={
        nothing
          ? '수확할 응답 피드백이 없습니다 — 세션에서 피드백을 받으면 여기서 평가 케이스로 수확합니다'
          : count > 0
            ? `미수확 피드백 ${count}건을 초안 평가 케이스로 수확합니다`
            : '새 피드백이 없습니다 — 기존 수확 문제집은 평가에서 볼 수 있습니다'
      }
    >
      <Badge count={count} size="small" offset={[-2, 2]}>
        <Button
          icon={<Icon name="experiment" />}
          loading={busy}
          disabled={nothing || count === 0}
          onClick={onHarvest}
        >
          피드백 수확
        </Button>
      </Badge>
    </Tooltip>
  )
}
