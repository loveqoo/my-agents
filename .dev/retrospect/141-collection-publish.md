# 141 — RAG 컬렉션 사용 공개(publish) (스펙 163)

실사용: "컬렉션 등록에 public/private 설정이 없어 남과 공유(공개)를 못 한다."

## 근인
컬렉션 사용은 `agent_may_wire`(스펙 113)로 게이트되는데, chat.py가 컬렉션 published를 **항상 False로
하드코딩**(`agent_may_wire(c.owner_id, False, ...)`)해 소유자 에이전트만 쓸 수 있었다. 같은 공개 장치가
MCP엔 이미 있었지만(published 플래그) 컬렉션만 빠져 있어 공유 길이 없었다.

## 배운 것
- **정정에서 배웠다: "이미 공유됨"이라 단정하기 전에 게이트를 끝까지 읽어라.** 처음 사용자에게 "컬렉션은
  이미 누구나 쓸 수 있다"고 답했다가, chat.py를 더 파보니 `agent_may_wire`(113) 게이트가 있어 **틀렸다**.
  사용자 보고("공유 못 함")가 내 단정과 어긋날 때 사용자가 맞았다([[probe-deeper-before-concluding]]).
  라우트 하나(list=전역)만 보고 사용 축을 유추하면 안 된다 — 배선 경로까지.
- **게이트 커버리지 정합(codex High) — installed≠covering의 교과서 사례**. published를 배선(agent_may_wire)
  에만 붙였더니 **직접 엔드포인트 `POST /search`가 게이트 없이 청크 본문을 유출**했다. "비공개=타인
  사용 차단"이 채팅에만 성립하고 직접 검색은 뚫림. 한 자원의 "사용"이 여러 입구(배선·직접검색·문서목록)
  를 가지면 **모든 입구에 같은 술어를 물려야** 한다([[installed-guard-isnt-covering-guard]]). `may_use_collection`
  단일 술어로 세 입구를 통일(drift 0).
- **세 축을 분리해 사고**: 가시성(list/get=전역, 존재/메타 노출)·관리(may_manage=소유자, 수정/삭제)·사용
  (may_use_collection=소유자|published|특권, 검색/문서/배선). publish는 *사용* 축만 연다. 축을 섞으면
  "공개했더니 남이 편집" 같은 사고. 직교 유지가 안전.
- **MCP 선례 미러로 설계 비용 절감**. published 컬럼·publish 라우트·agent_may_wire rule 4가 이미
  MCP에 있어 그대로 따라감(스키마·마이그레이션·토글 UI). 선례 답습이 일관성+검증 부담을 낮춘다.
- **위임 경계에서 fast-worker가 브리프 오류를 정정**: mockData.ts에 Collection 타입이 없어(실 API 전용)
  api.ts로 위치 바로잡고 보고. 또 Switch 클릭이 행 드로어로 전파되던 버그를 스모크로 잡아 stopPropagation.
  추측으로 안 채우고 발견·보고·범위내 수정 — 위임이 제대로 작동.

## 검증
verify_163 16/16(U1~4 agent_may_wire published flip·H1~4 publish 엔드포인트 권한·직교·멱등·H5~7 직접
search/documents 404-fold 봉인+publish 후 개방). codex High(search 우회)/Med(documents 메타) 둘 다 수정.
프론트 tsc 0·브라우저 스모크(공개 토글·배지 렌더·전파 버그 수정·콘솔 0).

## OUT
- 공개 컬렉션 목록 필터. 공개 시 PII/품질 경고. per-user 세밀 공유(rule 4는 전체 공개, MCP와 동일 입도).
- 평가 러너(resolve_search_collection 공용 경로)의 사용 게이트 — 엔드포인트 층서 막음, 러너는 별도(admin).

[collection-publish,gate-coverage-consistency,use-axis-orthogonal,mirror-precedent,dont-conclude-shared-before-reading-gate,delegation-corrects-brief]
