# 150 — RAG 공개/비공개 제거 (스펙 172, 163 되돌림) + 내가 틀린 것

구남님 교정: "public/private를 *수정 가능*하게 원한 건데, 공개/비공개 *상태를 추가*하는 방향으로
어긋났다. RAG에서 이 개념을 제외하라." → published 축 전면 제거 + "사용=전부 공용".

## 내가 틀린 것 (핵심 회고)
- **사용자가 "X를 못 한다"(공유 못 함) 할 때, 새 *기능*을 추가할지 기존 *속성*을 편집 가능하게 할지를
  먼저 갈랐어야 했다.** 구남님은 "public/private를 바꾸고 싶다"였는데, 나는 MCP publish 패턴을 *미러*해
  새 토글(공개/비공개 상태)을 얹었다. 결과=이미 있는 public/private(OwnerTag)와 내가 더한 공개/비공개가
  **중복**되어 혼란. **기존 패턴 미러링이 항상 옳은 게 아니다** — 이 케이스에 맞는 최소 해를 물었어야.
  [[craft-first-then-compound-as-asset]]: 과잉 구축은 크래프트가 아니다.
- **파괴적·모순 요청 앞에서 물은 건 옳았다.** 제거가 예전 그의 "공유하고 싶다"와 상충 → AskUserQuestion으로
  접근 모델(소유자만 vs 전부 공용)을 확인. 그가 "전부 공용" 선택. [[probe-deeper-before-concluding]] 적용.

## 배운 것
- **육안이 자동 체크가 놓친 걸 잡는다**(회고 133 재확인). 자동 체크 "공개 텍스트 없음"은 통과했으나,
  스크린샷을 보다 **"public" 태그(OwnerTag)가 남은 걸** 포착. 구남님의 "public/private"은 내 토글뿐
  아니라 그 소유 라벨도 포함이었다. 도구가 좁히고 육안이 확정.
- **기능 제거 = 그 기능의 테스트도 제거/갱신**(deep-reasoner 지적). verify_163이 이제 *뒤집힌* 불변식
  (bob search=404)을 검증 → 실행 시 실패하는 죽은 테스트. 제거는 그 불변식을 검증하던 테스트를 반드시
  갱신·폐기해야(안 그러면 stale 실패). verify_172로 대체([[move-breaks-references-both-directions]]의 테스트판).
- **불변 슬러그(name)로 배선 → 표시(alias) 변경이 안전**. 컬렉션 배선은 `Collection.name`(슬러그)로 하지
  표시명이 아니다. 그래서 가시성 라벨 제거·(후속 173) 별명 편집이 배선을 안 깬다. 정체성(name)과
  표시(alias) 분리의 배당.
- **접근 개방은 정적+라이브 둘 다로 검증**: deep-reasoner(관리 게이트 4개 온전·익명 401·잔여 0) +
  verify_172(비소유자 사용 200·관리 404·익명 401·publish 제거). 개방 변경일수록 "무엇이 안 열렸나"를 실측.

## 검증
verify_172 7/7 PASS(라이브 ASGI)·deep-reasoner 적대 검토(안전, Low=테스트 위생만→해결)·tsc clean·
마이그레이션 drop 적용·UI 스크린샷 육안(public/private·토글 전무).

## OUT
- 별명 편집(구남님 실제 의도)=스펙 173으로 별도. MCP published(McpServer)는 그대로. 스펙 163 doc·
  retrospect 141은 역사 기록으로 보존(163 INDEX 줄에 "172로 되돌림" 표기).

[collection-visibility,user-intent-editable-not-new-state,dont-mirror-pattern-blindly,eyeball-catches-what-check-misses,removal-must-retire-its-tests,wire-by-slug-display-rename-safe,verify-opening-both-static-and-live]
