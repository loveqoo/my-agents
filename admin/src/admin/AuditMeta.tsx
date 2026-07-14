/* 감사값 표시 공유 조각 (스펙 344) — 목록 셀 <AuditCell> + 상세 하단 <AuditFooter>.

   설계 원칙(스펙 344): 감사는 **주인공이 아니라 배경**이다. 목록엔 컬럼 하나(수정 시각·수정자)만
   늘리고 나머지 값은 툴팁·상세로 민다 — 4컬럼을 늘어놓으면 정작 이름·상태가 밀린다.

   actor 값 공간은 **열려 있다**(스펙 343 전제): 관리자 이메일 로컬파트 · 'system'(배경 작업) ·
   'unknown'(감사 도입 이전) · **추후 채팅으로 들어올 미등록 최종 사용자 ID**. 그래서
   - user 테이블 조인·프로필 링크·아바타를 쓰지 않는다(미등록 사용자에서 전부 빈칸이 된다),
   - "관리자 admin" 같은 **관리자 전용 라벨을 박지 않는다**(고객 ID가 합류하면 화면이 거짓말한다).
   지금은 system/unknown만 시각 구분하고, 주체 종류 배지(관리자/고객/시스템)의 자리는 비워둔다. */
import { Tooltip, Typography } from 'antd'
import type { Audit } from './mockData'
import { fmtDateTime, fmtTime } from './format'

const { Text } = Typography

/* 사람이 아닌/이력 없는 actor는 사람 이름처럼 보이면 안 된다 — 옅게 + 뜻을 툴팁으로. */
const SPECIAL: Record<string, string> = {
  system: '배경 작업(시드·배치·백그라운드 잡)',
  unknown: '감사 도입(스펙 343) 이전에 만들어진 기록',
}

export function Actor({ name }: { name?: string | null }) {
  if (!name) return <Text type="secondary">—</Text>
  const hint = SPECIAL[name]
  if (!hint) return <>{name}</>
  return (
    <Tooltip title={hint}>
      <Text type="secondary" italic>
        {name}
      </Text>
    </Tooltip>
  )
}

function full(a: Audit) {
  return (
    <div style={{ lineHeight: 1.7 }}>
      <div>
        생성: {a.created_by ?? '—'} · {fmtDateTime(a.created_at) || '—'}
      </div>
      <div>
        수정: {a.updated_by ?? '—'} · {fmtDateTime(a.updated_at) || '—'}
      </div>
    </div>
  )
}

/* 목록 셀 — "2시간 전 · admin". 4값 전체는 툴팁으로. */
export function AuditCell({ audit }: { audit?: Audit | null }) {
  if (!audit || (!audit.updated_at && !audit.updated_by)) return <Text type="secondary">—</Text>
  return (
    <Tooltip title={full(audit)}>
      <Text
        type="secondary"
        style={{
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          display: 'inline-block',
          maxWidth: '100%',
          verticalAlign: 'bottom',
        }}
      >
        {fmtTime(audit.updated_at)} · <Actor name={audit.updated_by} />
      </Text>
    </Tooltip>
  )
}

/* 상세·편집 화면 하단 메타 줄 — 한 줄로 4값 전부. */
export function AuditFooter({ audit }: { audit?: Audit | null }) {
  if (!audit || (!audit.created_at && !audit.created_by)) return null
  return (
    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 12 }}>
      <Actor name={audit.created_by} /> 생성 · {fmtDateTime(audit.created_at) || '—'}
      {'   |   '}
      <Actor name={audit.updated_by} /> 수정 · {fmtDateTime(audit.updated_at) || '—'}
    </Text>
  )
}
