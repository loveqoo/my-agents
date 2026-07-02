/* my-agents admin — 검색시험 드로어 셸 (스펙 097·126).
   공용 알맹이 `RetrievalTestPanel`을 antd Drawer로 감싼 얇은 래퍼 — 컬렉션 "검색 시험"(072)이 이 형태를
   쓴다(오른쪽 드로어). 메모리는 126에서 드로어를 벗고 패널을 상세 페이지에 인라인으로 쓴다.
   타입(RetrievalHit·SearchDiag·RetrievalOut)은 패널에서 재노출 — 기존 import 경로 보존. */
import { Drawer } from 'antd'
import { RetrievalTestPanel, type RetrievalHit, type RetrievalTestPanelProps } from './RetrievalTestPanel'

export {
  RetrievalTestPanel,
  type RetrievalHit,
  type SearchDiag,
  type RetrievalOut,
  type RetrievalTestPanelProps,
} from './RetrievalTestPanel'

export function RetrievalTestDrawer<H extends RetrievalHit>({
  open,
  title,
  onClose,
  ...panel
}: RetrievalTestPanelProps<H> & { open: boolean; title: string; onClose: () => void }) {
  return (
    <Drawer open={open} width={640} title={title} onClose={onClose} destroyOnHidden>
      <RetrievalTestPanel<H> {...panel} />
    </Drawer>
  )
}
