# 272 — 노드 문서 facet 승격: 도구에서 분리해 에이전트와 개념 정렬

> 271(기억 공용 컨트롤)에 이은 facet 정렬. 노드가 **도구+문서를 한 셀렉트에 접어** 둔 것을 분리해,
> 에이전트의 개념 구조(도구/문서 별도)와 맞춘다. 3부작의 "노드=에이전트 대칭" 연장.

## 배경 — 왜 이번엔 "공용 컨트롤"이 아니라 "facet 분리"인가 (정직)

271은 기억을 **공용 컨트롤**로 뽑았다 — 269가 죽은 선택지를 빼 장기가 **단일 옵션**이 됐기에 접이식
PickerGroup을 간결 인라인으로 무손실 하강할 수 있었다. **도구·문서는 다르다**: 카탈로그 스케일(MCP
서버·컬렉션 수십~수백)이라 에이전트의 `PickerGroups`(접이+검색+카운트, 스펙 107/109)가 인라인보다
낫다. 여기서 억지로 단일 공용 컴포넌트로 통일하면 한 surface(에이전트 스케일 or 노드 간결)를 훼손한다
(271 안 A의 위험·회고 246 "추출이 결합 드러냄"). 그래서 **이번 조각은 공용 컴포넌트가 아니라 노드의
facet 구조를 에이전트와 맞추는 것**: 노드도 도구/문서를 별개로 다루게 한다. 렌더 방식(PickerGroups vs
인라인)은 각자 밀도 보존(271 안 B 기조).

## 현재 구조 (측정)

- **노드**: 도구·문서가 `n.tools` **한 배열·한 셀렉트**에 접힘. 문서는 `search_documents__<컬렉션>`
  (스펙 268 P1, `safeToolName('search_documents', col)`)로 저장 — 도구 옵션에 "문서 검색 · <컬렉션>"으로
  섞여 노출(`nodeToolOptions` = MCP 도구 + 컬렉션). 저장 파생: `finalizeForm`이 `n.tools`의
  `search_documents__*`에서 `vectorTables`를 역산(무회귀).
- **에이전트**: 도구(`form.mcps`)·문서(`form.vectorTables`)가 **별도** PickerGroup. 개념·저장 모두 분리.

즉 노드만 둘을 섞어 노출한다 — 사용자가 "도구"를 고르는데 문서 검색이 섞여 나온다(경미한 혼란).

## 이 스펙의 범위 (노드 UI만 — 저장 스키마 무변경)

**저장은 `n.tools` 그대로**(268 P1·265 이름 해석 로드베어링 보존). **UI만** 도구/문서 두 컨트롤로 분리:

- **노드 도구 컨트롤**: MCP 도구만(값=`n.tools` 중 `search_documents__*` 아닌 것, 옵션=MCP 도구).
- **노드 문서 컨트롤**: 컬렉션만(값=`n.tools` 중 `search_documents__*`인 것, 옵션=컬렉션, 라벨=컬렉션명).
- 두 컨트롤의 onChange는 각자 담당 부분만 갈아끼우고 **나머지 `n.tools` 항목은 보존**해 합쳐 저장
  (도구 변경이 문서 항목을 떨구지 않게 — 회고 244 "필터는 원본 소비자 전수"의 쓰기판).
- 분리 술어: 문서 = `t === 'search_documents' || t.startsWith('search_documents__')`. 그 외 = 도구.
  (구저장 민이름 `search_documents`도 문서로 인식 — 무회귀.)

## 완료 조건 (측정 가능)

1. 노드 카드에 **도구·문서 컨트롤이 분리** — 도구 옵션에 "문서 검색 · …" 안 섞임, 문서 컨트롤은 컬렉션만.
2. **저장 왕복 무변경**: `n.tools`가 도구+문서 합집합으로 동일하게 저장(분리 전후 payload 동일) —
   도구만 바꿔도 문서 항목 보존·문서만 바꿔도 도구 항목 보존(e2e 왕복 단언).
3. `finalizeForm`의 `vectorTables`/`mcps` 파생 무변경(268 P1 회귀 — 실모델 노드 RAG e2e GREEN).
4. tsc 0·모바일 오버플로 0.

## 무회귀·경계

- `n.tools` 저장 스키마·백엔드·`_resolve_tool`(265)·`_rag_tools_for`(268) **무변경** — UI 표현만 분리.
- 도구/문서 쓰기 병합이 핵심 위험: 한 컨트롤 변경이 상대 항목을 떨구면 저장 손실 → **병합 보존**을
  단위+e2e로 단언(양방향).
- 에이전트 폼은 이번 범위 밖(이미 분리). 공용 컴포넌트 통일은 스케일 패러다임 충돌로 반려(위 정직 절).

## 검증 (사다리 3단)
- 단위: 도구/문서 분리·병합 순수함수(도구 변경→문서 보존, 역도, 구저장 민이름 인식).
- e2e: 노드 카드에서 도구·문서 각각 선택→저장 왕복 `n.tools` 합집합 불변(기능적). 268 노드 RAG 실모델 무회귀.
- 적대(codex): 병합이 항목을 떨구/중복하지 않는지, 문서 술어가 MCP 도구(`server__tool`)를 오분류 안 하는지
  (예: 서버명이 search_documents인 MCP — 경계), 파생 무회귀.

### 검증 결과
- **verify-272-node-documents.mjs 9/9 GREEN**(분리·병합 보존·저장 왕복 `n.tools=["web-fetch__wiki_search",
  "search_documents__docs-kb"]` 합집합 보존). 268 노드 RAG 실모델·270 e2e 무회귀. tsc 0.
- **codex 적대 리뷰 — High/Medium = 측정상 도달 불가 오탐(정직 경계, [[complement-attack-can-be-honest-boundary]] 판정)**:
  codex는 "서버명 `search-documents`인 MCP → 런타임명 `search_documents__foo` → 문서로 오분류(High), 같은 컬렉션
  중복(Medium)"을 주장. **측정으로 반증**:
  - `safeToolName`은 **대시를 보존** → 유효명 `search-documents`는 `search-documents__foo`(대시)라 `isDocTool`
    접두(`search_documents__`, 밑줄)에 **안 걸림**(isDoc=false).
  - 밑줄로 sanitize되는 이름(`search_documents`/`search.documents`/`search documents`)은 **NAME_RULE이 금지**
    — 프론트 `naming.ts`·백엔드 `naming.py` 둘 다 `^[a-z0-9\-]+$`(밑줄·점·공백·대문자·한글 불가). 서버가
    `blocks.py:46 validate_resource_name`로 거부하므로 충돌 이름 자체가 **생성 불가**.
  - 즉 두 보증(대시 보존 + 밑줄 금지)이 충돌을 원천 차단 → codex가 가정한 collision path는 **미도달**.
  - 미래 규칙 완화(밑줄 허용)에 대비해 `isDocTool`에 **불변식 명시 주석**을 못박음(243 ① 예약 이름공간 규율).
- **codex Low(레거시 민이름 `search_documents` 드롭)** = 수용/OUT: 문서 컨트롤을 명시적으로 비우면 구저장
  전체-컬렉션 민이름이 떨어지나, 이는 폐기된 형식이고 비우기는 명시 의도라 정직 경계. 신규 저작은 컬렉션별.

## 산출 후
INDEX.md 한 줄 + per-spec 커밋(272). 남은 facet: 모델(이미 유사)·프롬프트(선택 vs 작성, 성격차)는
후속 판단.
