/* my-agents admin — 검색시험 드로어 셸 (스펙 097·126).
   공용 알맹이 `RetrievalTestPanel`을 antd Drawer로 감싼 얇은 래퍼 — 컬렉션 "검색 시험"(072)이 이 형태를
   쓴다(오른쪽 드로어). 메모리는 126에서 드로어를 벗고 패널을 상세 페이지에 인라인으로 쓴다.
   (타입 재수출 배럴은 소비자가 사라져 제거 — 스펙 324. 타입은 RetrievalTestPanel에서 직접 import.) */
import { Drawer } from 'antd'
import { RetrievalTestPanel, type RetrievalHit, type RetrievalTestPanelProps } from './RetrievalTestPanel'

export function RetrievalTestDrawer<H extends RetrievalHit>({
  open,
  title,
  onClose,
  ...panel
}: RetrievalTestPanelProps<H> & { open: boolean; title: string; onClose: () => void }) {
  return (
    <Drawer open={open} size={640} title={title} onClose={onClose} destroyOnHidden>
      <RetrievalTestPanel<H> {...panel} />
    </Drawer>
  )
}
