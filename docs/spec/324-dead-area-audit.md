# 324 — 죽은 영역 감사 (dead-area audit)

## 배경 / 동기

사용자 원칙(2026-07-13): **"새 기능을 넣는 것보다 죽은 영역을 식별하지 못한 게 더 위험하다."**
스펙 323에서 죽은 라벨("단기(세션)")이 걸러내는 코드 ~11곳과 함께 살아남아 사용자를 혼란시킨 사례가
원형. 죽은 영역은 조용히 자라며 "이미 처리됨" 착시를 만들므로, 1회 전수 감사로 후보를 식별한다.

## 죽은 영역의 냄새 축 (스캔 단위)

| 축 | 정의 | 원형 사례 |
|---|---|---|
| A. 배제로만 참조되는 값 | 생성·사용은 없고 필터·배제만 되는 enum/라벨/상수 | 단기(세션) (323) |
| B. 써놓고 안 읽는 필드 | config/DB에 기록되지만 어떤 코드도 읽지 않는 키 | — |
| C. 죽은 코드 | 미사용 함수·export·컴포넌트·라우트(호출자 0) | — |
| D. 아무것도 안 지키는 가드 | 검사 지점과 부수효과 지점이 어긋나 실효 0인 검사 | 리다이렉트 SSRF (학습) |
| E. 고아 데이터 | API로 도달 불가능한 DB 행(소유자 소멸·참조 끊김) | _verify* 고아 (321) |
| F. 버려진 스펙 잔재 | 폐기된 방향의 코드·주석·마이그레이션 흔적 | 트리노드 그래프빌더 폐기 |

## 실행

- deep-reasoner 4기 병렬(읽기 전용): ①백엔드(A·B·C·D) ②프론트(A·C) ③시드·카탈로그·config 스키마(B·F)
  ④DB 고아(E — 읽기 쿼리만). 각자 자기완결 프롬프트 + 증거(file:line)·확신도 필수.
- 메인이 종합: 후보를 **확실(즉시 제거 가능) / 유력(검증 필요) / 관찰(백로그)** 3급으로 분류.
- **이번 스펙은 식별·보고까지.** 제거는 후보별 별도 승인(확실분은 후속 스펙 또는 이 스펙 연장으로).

## 제외 (이미 알려진 죽은 영역 — 중복 보고 방지)

- `tests/verify_*.py` 159개 raw 스크립트(스펙 321서 판정: 스위트 격리는 백로그 대형 항목).
- `docs/` 인간 영역 문서(감사 대상 아님).

## 완료 조건

- 축 A~F 전수 스캔 보고서(증거 포함) + 3급 분류 목록.
- 확실분에 대한 제거 제안(사용자 승인 대기).
- 재발 방지 장치 후보(훅/CI 패턴 검사) 1개 이상 제안.

## 감사 결과 (2026-07-13, 4기 스캔 + 사용자 승인 후 제거 실행)

### 발견 → 처리

| 급 | 발견 | 처리 |
|---|---|---|
| 확실 | **세션 상태 버킷 4종**(awaiting/error/running/draining) — Session.status 쓰기는 active(chat_persist)·completed(/end) 뿐, "승인 대기 (0)"·"오류 (0)" 탭 영구 0, detail.awaiting/error는 스키마에 없는 필드 | **제거**(사용자 선택: 배선 대신 삭제) — 버킷 live=active만, 프론트 탭·Alert·status 유니온·SESSION_STATUS 맵·DebugChat 라벨 축소 |
| 확실 | AGENT_SOURCE 상수(참조 0, stale 주석만) · getA2ASkills+A2ASkill(호출 0) · IdRow(참조 0) | **제거** |
| 확실 | DB 테스트 잔재 — 센티넬/삭제유저 소유: approvals 226·sessions 196·suite-kb 컬렉션·eval_datasets 3·mem0 39 + **데모 화석 세션 2행**(idle·error, 스펙 303 이전 시드 잔재) | **삭제**(SELECT로 전수 분포 확인 후 — 실사용 흔적 없음, 전부 UUID형 기계 유저) |
| 확실 | (323 잔존) agents.config 단기(세션) 3건 — 323 측정이 agent_versions만 봄 | **즉시 봉합**(agents 0/versions 0 재측정) |
| 유력 | 메모리 히트 `type` 필드 — 항상 "semantic" 하드코딩(정보 0), 폐기 분류(의미/일화/절차)의 화석, Inspector purple 분기 도달 불가 | **제거**(저위험 승인분) — MemoryHit·Memory 인터페이스·두 백엔드 상수·태그 |
| 유력 | RetrievalTestDrawer 재수출 배럴(옛 경로 소비자 소멸) | **제거** |
| 유력 | POST /eval/generate-dataset(호출 0) · Chunk.token_count(읽기 0, DROP=마이그레이션) | **백로그**(사용자 확인/별도 검증 후) |
| 관찰 | _harness088.tsx(의도적 비연결일 수 있음) | **백로그**(보존 의사 확인) |

### 깨끗함 확인
시드 카탈로그 전 항목 소비 추적 OK · config JSONB 키 전수 읽힘(write-only 0) · Cedar/그래프빌더 잔재 0 · FK 무결성 0 · agent_versions 고아 0.

### 기각한 가설 (오탐 방지 — 다음 감사가 같은 길 안 가게)
- `GET /_remote/sdk/.well-known/agent-card.json` 죽은 라우트? → **기각**: 리터럴 grep 0이지만 fetch_card가 well-known을 자동 부착해 실호출(정적 호출자 0 ≠ 죽음의 대표 사례).
- `CompiledStateGraph` 미사용 import(vulture 90%)? → **기각**: 따옴표 forward-ref 반환타입에서 사용(vulture가 문자열 타입주석 못 봄).
- AgentConfig 18필드 중 write-only? → **기각**: 전부 라운드트립 읽기 실재.
- `ToolApprovalOverride`·`AgentCard` unused export(knip)? → **기각**: 같은 파일 내부 사용 — 죽은 코드가 아니라 과노출.
- `mockData.ts` = mock 잔재? → **기각**: 이름과 달리 가짜 레코드 0, 순수 타입+상수 모듈(실서버 모드도 소비).
- seed의 `manifest`/`deploy` 키 드롭? → **기각**: AgentConfig가 아니라 A2A 카드 확장(connect 분류가 읽음).
- calc-tools·web-fetch 시드 MCP가 에이전트 미참조라 죽음? → **기각**: admin에서 배선 가능한 능력(플랫폼 목적상 정상 대기).

### 감사 중 발견한 기존 이슈(324 밖, 백로그행)
- `make suite` `pipeline-rag-and-tool` flaky 악화 — echo 도구 바인딩은 정상(측정), qwen3.6이 도구 호출을 자주 건너뜀(모델 행동, 코드 회귀 아님 — stash 재현으로 확증).
- `make complexity` rag.py `reindex_collection` rank D(스펙 312 이후 드리프트).
- ruff format 드리프트 9파일 — 별도 커밋으로 선행 정리(PY_SRC 한정).

### 검증
- tsc/build·ruff/mypy(108파일)·suite 부분(pipeline-memory-recall ok — MemoryHit 변경 후 회상 e2e) 통과.
- 세션 화면 기능 검증(Playwright): 탭 전체/라이브만·목록 20행·상세 드로어·라이브 필터 동작, 스크린샷 육안.
- DB: 고아 재측정 0 · status 분포 active/completed만.
- codex 적대 리뷰(제거물의 남은 소비자·여집합 공격).

### 재발 방지 제안(후속 후보)
- "배제로만 참조되는 값" 등 냄새 축의 주기 감사를 스킬화(dead-area-audit 커맨드) — 이번 4기 프롬프트가 원형.
