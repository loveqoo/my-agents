# 147 — 에이전트 분류 최소 어휘 + private 정책 (사용자 계위 채택)

## 확정 모델 (사용자 트리 + 최소 어휘안 합의)
- 태그 3개뿐: **public**(모두 도구처럼 사용) / **private**(소유자만 사용) / **external**(가져다 씀 — 소유 태그 없음)
- **A2A는 스위치(켬/끔)** — shared/non-shared 별도 단어 없음(스위치 이름이 축)
- 트리 불변식: **private → A2A 불가**(말이 안 되는 조합은 UI·API에서 제거), external → 항상 사용 가능
- 매핑: public=owner 없음(관리자 저작), private=owner 있음. 승격(private→public)은 OUT(후속).

## 정책 (동작 변경 — 라벨 그 이상)
1. **A2A 게이트**: private 에이전트 노출 시도 → 400. UI 스위치 비활성+사유 툴팁(리스트·드로어).
   기존 데이터에 "노출된 private"가 있으면 일괄 끔(정직 정리 — 로그).
2. **사용 게이트**: private 에이전트 채팅 → 소유자·admin 외 403.
3. **가시성**: 일반 사용자 목록에서 타인 private 제외(admin·machine=전부). 플레이그라운드도
   같은 목록을 쓰므로 자동 적용.
4. 브로커 위임의 agent 능력은 기존 소유 게이트(learning 070) 유지 — codex로 재확인만.

## UI
- OwnerTag: public(회색)/private(파랑)/private·타인(주황, admin 시야용). external 행은 소유 태그 생략.
- A2A 컬럼 'A2A', 스위치 텍스트 켬/꺼짐. private면 disabled+툴팁. 드로어 문구 동조.
- 필터·태그 안내 갱신(어휘 3개 기준).

## 검증
- verify_147: 노출 400·타인 private 채팅 403(멤버 주체 스텁)·목록 필터(멤버=타인 private 불포함,
  admin=전부)·기존 노출 private 정리. e2e: 태그 3종·private 스위치 비활성. **codex 필수**(권한 경로).
