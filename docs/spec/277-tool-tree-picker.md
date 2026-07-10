# 277 — 도구 선택을 서버→도구 계층 트리(antd Tree)로

> 사용자 요청(276 직후): "도구 선택을 리치한 컴포넌트로 — [x] some-tools / [x] tool-a / [x] tool-b".
> 276이 도구 단위 배선을 열었으니, 평면 `서버 · 도구` 나열 대신 **서버(부모)→도구(자식) 체크박스
> 트리**로 계층을 드러낸다. 부모 체크=그 서버 도구 전체 선택, 부분 선택=indeterminate.

## 설계

**공용 `ToolTree`**(admin/CLAUDE.md: 선택 위젯=antd `Tree` checkable):
- 입력: `servers: {name, tools: string[]}[]`(카탈로그=blocks.mcp.items), `value: string[]`(런타임명
  server__tool, 스펙 276), `onChange(next: string[])`, `emptyText`.
- treeData: 서버=부모 노드(key=`srv:<name>`), 도구=자식 리프(key=`safeToolName(server, tool)`=런타임명).
  카탈로그에 도구 없는 서버는 트리에서 제외(배선 불가·mcps 보존 셋이 담당 — 276과 동일).
- 체크 상태: antd 비-strict 모드가 리프 checkedKeys에서 부모 체크/indeterminate 자동 파생. onCheck의
  checked에서 `srv:` 부모 키를 걸러 **리프(런타임명)만** onChange.
- 리치: 카탈로그 스케일 대비 검색 Input(서버명·도구명 필터·매칭 자동 확장), 선택 수 배지.

**통합(세 표면, 값=런타임명 동일)**:
- **직접형 폼**: doGroups에서 '도구' 제거→ToolTree로. onChange=`setTools`(tools 교체 + mcps 서버
  합집합 파생, 276 규칙). 문서는 PickerGroups 유지(컬렉션=평면, 계층 없음 — 247 "데이터 모양대로").
- **노드 카드**: 도구 Select→ToolTree(value=`n.tools.filter(!isDocTool)`, onChange 시 문서 항목 보존
  병합, 272). 문서 Select는 아래 유지.
- **오버라이드**: 비-조율형 도구 PickerGroup→ToolTree(draft.tools 교체+mcps 파생). 조율형(위임
  capGroups)은 무변경.

## 완료 조건 (측정 가능)
1. 세 표면에 트리 렌더 — 서버 부모 + 도구 자식 체크박스(e2e: 부모/자식 노드 존재).
2. 부모 체크→그 서버 도구 전체 선택(런타임명 전부 value에), 부분→indeterminate(e2e).
3. 자식 하나 체크→value=그 런타임명 1개, 저장 왕복 `config.tools` 일치(직접형 e2e).
4. 노드: 도구 트리 변경이 문서 항목 보존(272 병합 무회귀).
5. 저장 파생: 직접형 mcps=선택 도구의 서버 합집합(276 무회귀), 승인 목록=선택 도구만.
6. tsc 0 + 272~276 무회귀 + 모바일 오버플로 0.

## 무회귀·경계
- 저장 스키마·백엔드 무변경(값=런타임명, 276 그대로). UI 위젯만 교체.
- 문서·기억은 트리 대상 아님(평면 카탈로그·단일 옵션). 조율형 위임 피커 무변경.
- 검증: e2e(트리 상호작용+저장 왕복+병합 보존)+형제 회귀. codex — UI 전용·값 무변경이라 스킵 검토.

### 검증 결과
- **verify-277-tool-tree.mjs 9/9 GREEN** — ① 직접형 서버 부모+도구 자식 노드 ② 자식 체크→저장
  config.tools 1개·mcps 파생 ③ 부모 체크→서버 도구 전체(web-fetch 부모→wiki_search+wiki_page)
  ④ 노드 카드 트리+문서 병합 보존 ⑤ 오버라이드 트리. tsc 0·모바일(360px) 오버플로 0·육안 캡처.
- **형제 회귀(트리 전환으로 낡음, 246 ④ — 셀렉터 갱신·불변식 유지)**: 272(도구 Select→트리 노드
  체크)·273(도구 PickerGroup→트리 존재)·274(배치 라벨 '도구 (선택)'→'도구'+순차 커서 탐색 — 안내
  문구에도 '도구' 있어 단순 indexOf 깨짐)·276(도구 체크박스→트리 노드·하이드레이션 배지)·109(P5
  피커→트리) 전부 갱신 후 GREEN. 275·268 무영향.
- **codex 스킵(사유)**: 값=런타임명(276 그대로)·저장/백엔드 무변경·위젯 표현만 교체 — 276에서 이미
  도구 배선 경계를 적대 검증. 사용자 원하면 후속 가능.
