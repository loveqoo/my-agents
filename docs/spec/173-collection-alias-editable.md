# 173 — RAG 컬렉션 별명(alias) 편집 노출 (생성자만)

## 배경
개발자 실제 의도(스펙 172 교정에서 드러남): "public/private를 *수정 가능*하게" = 컬렉션의 **표시 속성을
편집**하고 싶다. 별명(alias)이 바로 그 자유 표기 표시명(스펙 148). "어짜피 별명으로 연결하는 거 아니까."

## 이미 되어 있는 것 (구현 불요)
- 백엔드 `update_collection`(PUT /{cid})이 `c.alias`를 세팅 — **소유자만**(assert_may_manage). 새 API 불요.
- 프론트 `updateCollection`이 `alias?: string|null` 받음.
- **배선은 `Collection.name`(슬러그)으로** 하지 별명이 아니다(chat.py `Collection.name.in_(vt_names)`).
  → 별명 편집은 **순수 표시 변경, 배선 무영향**(개발자 "별명으로 연결"은 실은 name으로 연결 — 그래서 더 안전).

## 유일한 갭
편집 UI(CollectionsView `DocsDrawer`의 "컬렉션 설정" 패널)가 별명 입력을 안 노출. 생성 모달엔 있는데
편집 폼엔 설명·청크 정책만 있음.

## 딜리버러블 (프론트만)
`CollectionsView.tsx` DocsDrawer:
1. `alias` 상태 추가 + `useEffect`로 `collection.alias ?? ''` 로드.
2. "컬렉션 설정" 패널에 "별명" Input 추가(설명 위).
3. `savePolicy`의 `updateCollection` 호출에 `alias: alias.trim()` 포함.
   - 비우기: `""` 전송 → 백엔드 `"".strip() or None` → 별명 제거(null 전송은 "미변경"이라 안 됨).

## 검증
- tsc clean. 브라우저: 편집 폼에 "별명" 입력 노출·현재 값 프리필·저장 후 목록에 반영(alias||name 표시).
- 소유자만: 백엔드 assert_may_manage가 비소유자 저장을 404(스펙 172 verify로 이미 확인된 관리 축).

## OUT
- name(슬러그) 편집(불변 식별자 — 별도 축). 별명 유일성(자유 표기라 중복 허용).
