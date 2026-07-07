/* 스펙 209 — 응답 피드백 버튼(👍/👎 + 선택 이유). 재사용: 세션 뷰·플레이그라운드(예정).
   antd Button/Popover/Input 조립(모든 UI antd 규칙). 한 번 클릭=평점 upsert, 재클릭=취소(토글),
   평점 있으면 '이유' Popover로 사유 추가/수정. 서버가 소유권·assistant-only 게이트하므로 여기선
   낙관 갱신만(실패 시 message.error·이전 값 복원은 상위 onChange가 서버 응답으로 확정). */
import { useState } from 'react'
import { Button, Popover, Input, Tooltip, Space, message } from 'antd'
import { LikeOutlined, LikeFilled, DislikeOutlined, DislikeFilled } from '@ant-design/icons'
import { setMessageFeedback, clearMessageFeedback, type MessageFeedback } from './api'

export function FeedbackButtons({
  sessionId,
  messageId,
  value,
  onChange,
}: {
  sessionId: string
  messageId: string
  value: MessageFeedback | null | undefined
  onChange: (fb: MessageFeedback | null) => void
}) {
  const rating = value?.rating ?? null
  const [reason, setReason] = useState(value?.reason ?? '')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const apply = async (r: 'up' | 'down') => {
    if (busy) return
    setBusy(true)
    try {
      if (rating === r) {
        await clearMessageFeedback(sessionId, messageId)
        onChange(null)
      } else {
        const fb = await setMessageFeedback(sessionId, messageId, r, reason)
        onChange(fb)
      }
    } catch {
      message.error('피드백 저장에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  const saveReason = async () => {
    if (!rating || busy) return
    setBusy(true)
    try {
      const fb = await setMessageFeedback(sessionId, messageId, rating, reason)
      onChange(fb)
      setOpen(false)
    } catch {
      message.error('이유 저장에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space size={2}>
      <Tooltip title="좋아요 — 이 답을 유지 지표로">
        <Button
          type="text"
          size="small"
          aria-label="좋아요"
          icon={rating === 'up' ? <LikeFilled style={{ color: 'var(--color-success)' }} /> : <LikeOutlined />}
          onClick={() => apply('up')}
        />
      </Tooltip>
      <Tooltip title="싫어요 — 이 답을 회귀 방지 지표로">
        <Button
          type="text"
          size="small"
          aria-label="싫어요"
          icon={rating === 'down' ? <DislikeFilled style={{ color: 'var(--color-error)' }} /> : <DislikeOutlined />}
          onClick={() => apply('down')}
        />
      </Tooltip>
      {rating ? (
        <Popover
          open={open}
          onOpenChange={setOpen}
          trigger="click"
          title="이유 (선택 — 평가 기준 재료)"
          content={
            <div style={{ width: 260 }}>
              <Input.TextArea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                placeholder="왜 그렇게 평가했나요?"
              />
              <div style={{ textAlign: 'right', marginTop: 8 }}>
                <Button size="small" type="primary" loading={busy} onClick={saveReason}>
                  저장
                </Button>
              </div>
            </div>
          }
        >
          <Button type="text" size="small">
            {reason ? '이유 ✓' : '이유'}
          </Button>
        </Popover>
      ) : null}
    </Space>
  )
}
