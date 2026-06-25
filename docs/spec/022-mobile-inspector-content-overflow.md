# 022 — 모바일 인스펙터 콘텐츠 오버플로 픽스 + 전 페이지 모바일 회귀 검증

## 배경 / 증상

플레이그라운드의 **턴 인스펙터**가 모바일(`!screens.lg`)에서 전체 화면 오버레이
(`position:fixed; inset:0; zIndex:1200`, `<Inspector fullWidth />`)로 렌더된다.
사용자(아이폰 사용자) 보고: **"특정 콘텐츠가 깨짐"**.

초기 실측(시드 데이터, 짧은 텍스트)에서는 오버플로가 재현되지 않았다 →
내 측정이 사용자 보고와 어긋남 → memory `probe-deeper-before-concluding`에 따라
**측정을 의심**하고 적대적 콘텐츠 픽스처(`_fixture.tsx`, 긴 URL/토큰/식별자/다수 태그)로
재현. 아이폰 크기(SE 375 / 13 390 / 14 Pro Max 430) 전부에서 인스펙터 내부 요소가
`aside` 밖으로 넘침을 확인.

## 원인 (017에서 shared 컴포넌트엔 적용했지만 playground 인스펙터는 별도라 누락)

줄바꿈/`flexWrap` 보호가 없는 텍스트·태그 노드가 끊김 없는 긴 콘텐츠에서 가로 오버플로.
learning 018(모바일 오버플로 근본 원인 패턴)과 동일.

| # | 위치 | 문제 | 픽스 |
|---|------|------|------|
| 1 | L259 시스템 프롬프트 태그 행 | `flexWrap` 없음 → 메모리 타입 태그 다수가 우측으로 줄줄이 넘침 (최대 범인) | 행에 `flexWrap:'wrap'`, 세로갭 추가 |
| 2 | L260 `agent.name` Tag | 긴 이름이 한 태그에서 안 끊김 | Tag에 `whiteSpace:'normal'; height:'auto'; maxWidth:'100%'` |
| 3 | L276/279 메모리 스코프 Tag | 긴 user_id/run_id 식별자 안 끊김 → 넘침 | Tag에 `whiteSpace:'normal'; wordBreak:'break-all'; height:'auto'; maxWidth:'100%'` |
| 4 | L102 MemoryRow text | 끊김 없는 긴 토큰 보호 없음 | `overflowWrap:'anywhere'` |
| 5 | L120 McpCall server.tool span | 긴 서버/툴명 보호 없음 | 부모 행 `minWidth:0`, span에 `overflowWrap:'anywhere'`, 행 `flexWrap` 검토 |
| 6 | L128 McpCall result div | 긴 결과 텍스트 보호 없음 | `overflowWrap:'anywhere'` |
| 7 | L152/153 GraphPath 노드명 | 긴 노드명 안 끊김 → 넘침 | 내부 flex에 `minWidth:0`, 노드명 span `wordBreak:'break-all'`, 행 `flexWrap` |

`codeBox`(L65)는 이미 `whiteSpace:pre-wrap; wordBreak:break-word; overflow:auto`로 안전.

## 범위

- **수정 1개 파일**: `admin/src/playground/Inspector.tsx` (순수 프레젠테이션, 콘텐츠 줄바꿈 보호만 추가).
- 너비 독립적 픽스 → 데스크톱 384px 패널에서도 동일 콘텐츠로 깨지던 것 함께 해결.
- **전 페이지 회귀 검증**: 6개 어드민 뷰(overview/agents/blocks/models/sessions/approvals)는
  017에서 모바일 최적화 완료(grid auto-fit, table→card, Drawer overflow:hidden, Desc 세로 스택).
  신규 작업 아님 → **회귀 검증만**. + playground = 총 7개 뷰.

## 검증 (사용자 지시: "playwright로 꼼꼼하게", "아이폰 디스플레이 크기")

1. 픽스처 프로브 재실행 → 아이폰 3종(375/390/430)에서 `aside` 내부 오버플로 **0** 확인.
2. 실 앱 Playwright 스윕 → 7개 뷰 전부 아이폰 3종에서 `documentElement`/스크롤 컨테이너
   가로 오버플로 없음 확인 (회귀 가드). 가능하면 `tests/e2e/specs/`에 정식 스펙으로.
3. `tsc --noEmit` 타입 무오류.
4. 타자 검증: 서브에이전트/codex로 diff 비판적 리뷰.

## 완료 조건

- [x] Inspector.tsx 7개 오프endер 픽스 적용
- [x] 픽스처 프로브: 아이폰 3종 오버플로 0
- [x] 실 앱 스윕: 7개 뷰 × 아이폰 3종 가로 오버플로 0 (mobile-overflow.spec.ts, 27 passed)
- [x] tsc 무오류
- [x] 타자 검증 통과 (codex GATE PASS, P1 없음; P2·일관성 권고 반영)
- [x] 임시 파일 정리(inspector-fixture.html, _fixture.tsx, scratch-*.mjs, *.png)
- [x] Compounding: retrospect 014 + learning 024
- [ ] **main 머지 금지** (사용자가 브랜치에서 직접 테스트)
