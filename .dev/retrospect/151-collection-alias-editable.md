# 151 — RAG 컬렉션 별명 편집 노출 (스펙 173)

스펙 172 교정에서 드러난 개발자 *실제* 의도("수정 가능한 표시 속성")를 최소 변경으로 충족.

## 한 것
편집 드로어(DocsDrawer "컬렉션 설정")에 별명 Input 추가 + savePolicy에 `alias: alias.trim()` 포함.
프론트 3줄대. 백엔드(update_collection이 alias 세팅, 소유자만)·API(updateCollection이 alias 받음)는
이미 있었음 — 갭은 UI 노출뿐.

## 배운 것
- **"기능 없음"이 아니라 "노출 안 됨"인 경우가 있다**. 별명 편집은 백엔드·API 다 준비돼 있었고 생성
  모달엔 입력도 있었는데 *편집* 폼에만 빠져 있었다. 새로 만들기 전에 **이미 있는지부터** 봤어야(스펙 172
  때 내가 새 토글을 얹은 과잉과 대비 — 172는 없는 걸 잘못 만들었고, 173은 있는 걸 노출만).
- **정체성(name 슬러그) / 표시(alias) 분리가 편집을 안전하게 만든다**. 배선은 name으로 하니 별명을
  아무리 바꿔도 에이전트 연결 무영향 — "이름표만 갈아끼우기". 사용자의 "별명으로 연결" 오해를 정정하되
  결론(별명 편집)은 옳았고 오히려 더 안전.
- **비우기 시맨틱 함정**: 별명 제거는 `null`이 아니라 `""` 전송이어야 백엔드 `"".strip() or None`이 지운다
  (null=미변경). 저장에 `alias.trim()`을 보내 빈 입력이 제거로 이어지게. 브라우저 V4(비우기 원상복구)로 실측.

## 검증
tsc clean. 브라우저 e2e 4/4(별명 입력 노출·프리필·저장 토스트·목록 반영·비우기 원상복구). 스크린샷
육안(행이 "문서 지식베이스(별명시험) docs-kb" 표시 — alias 표시·name 슬러그 병기).

## OUT
- name(슬러그) 편집=불변 식별자라 별도 축. 별명 유일성 미강제(자유 표기).

[collection-alias,not-missing-just-unexposed,identity-vs-display-separation,clear-via-empty-not-null,check-existing-before-building]
