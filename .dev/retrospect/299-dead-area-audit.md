# 299 — 죽은 영역 감사 + 확실분 제거 (스펙 324)

## 무엇을 했나

사용자 원칙 "새 기능보다 죽은 영역을 식별하지 못한 게 더 위험하다"에서 출발. deep-reasoner 4기 병렬
스캔(백엔드/프론트/시드·스키마/DB 고아) → 3급 분류 보고 → 사용자 승인 → 확실분+저위험 유력분 제거.
가장 큰 발견: **세션 상태 버킷 4종(awaiting/error/running/draining)이 한 번도 생산된 적 없는 죽은
분류**였고, 그 위에 "승인 대기 (0)"·"오류 (0)" 탭과 스키마에 없는 필드(detail.awaiting/error)를 읽는
죽은 UI까지 쌓여 있었다.

## 핵심 배운 것

### 1) 감사가 감사자를 잡았다 — 내 청소(323)의 미완을 다음 감사가 발견
DB 스캐너가 `agents.config`에서 단기(세션)을 발견하고 "정상(오탐)"으로 기각했는데, 그건 323에서 내가
지웠다고 보고한 가짜 라벨이었다. 323의 "FAKE 0" 측정이 **agent_versions만 보고 agents(현재 스냅샷)를
안 본 것**. 같은 데이터가 두 테이블에 사는 구조에서 한쪽만 측정하면 "0"이 거짓이 된다.
**측정의 완료선언은 그 값이 사는 모든 장소를 열거한 뒤에** — 그리고 주기 감사는 이런 미완을 잡는
그물이 된다(이번 발견 자체가 감사의 가치 실증).

### 2) 죽은 상태는 층층이 쌓인다 — 값→분류→UI→필드까지 한 사슬
awaiting/error는 (a) 백엔드가 안 쓰는 status 값 → (b) 그 값을 기다리는 버킷 분류 → (c) 영구 0인
필터 탭 → (d) 스키마에 아예 없는 필드를 읽는 Alert까지 4층으로 자랐다. 죽은 값 하나를 방치하면
그 위에 소비 코드가 계속 쌓여 "동작하는 것처럼 보이는 UI"가 된다(회고 067의 "겉도는 죽은 상태"와
동형). 제거도 사슬 전체를 한 번에 — 유니온 타입 축소가 tsc로 나머지 사슬(running 스피너 분기)을
자동으로 찾아줬다(**타입을 좁히면 컴파일러가 죽은 분기를 대신 찾는다**).

### 3) 스캐너 판정도 재검증 대상 — "절대 생산 안 함"과 DB 실물의 충돌
스캐너는 "코드가 awaiting/error를 절대 안 쓴다" 했는데 DB엔 error·idle 세션이 실존했다. 파보니
**스펙 303 이전 데모 시드의 화석**(코드는 이미 제거, 행만 잔존). 판정과 실물이 어긋나면 어느 쪽이
낡았는지 파야 한다 — 이번엔 둘 다 옳았다(현재 코드 기준 판정 vs 과거 코드의 잔재). 화석 2행을 지워
축소된 상태맵과 DB를 정합시켰다(안 지웠으면 `SESSION_STATUS[st]` undefined 크래시 지뢰).

### 4) 격리된 검증 실패는 stash 재현으로 가른다
검증 중 `make suite` 실패(pipeline-rag-and-tool)와 `make metrics-fast` 실패(format 9파일·complexity D)를
만났다. **git stash 후 재실행**으로 셋 다 내 변경 전부터 있던 기존 드리프트임을 확증 — suite는 모델
(qwen3.6)이 echo 도구 호출을 자주 건너뛰는 flaky(도구 바인딩은 측정으로 정상 확인), format은 최신
ruff 규칙 드리프트(별도 커밋으로 선행 분리), complexity는 스펙 312 이후 잔재. "내 탓인가"를 가르는
가장 싼 방법 = stash 재현. 단, format 정리 때 `packages` 전체에 돌려 alembic까지 재포맷한 실수 →
reset 후 PY_SRC 한정 재커밋(마이그레이션은 역사 기록, 도구 스코프는 repo 관례를 따른다).

### 5) 적대 리뷰가 잡는 것은 "옆 파일" — 잔존 소비자 3곳
직접 grep으로 다 지웠다고 생각한 뒤에도 codex 그물에 RecallPanel `{h.type}` 렌더·api.ts MemoryHit
인터페이스 type·schemas.py 주석이 걸렸다. 삭제 작업의 여집합 = "제거물의 남은 소비자"이고, 이건
삭제한 파일이 아니라 **옆 파일**에 있어서 자가 grep 키워드가 안 닿기 쉽다(인터페이스명이 백엔드와
프론트에서 동명이지만 별개 정의인 것도 함정).

## 검증
- tsc/build·ruff/mypy(108파일)·suite 부분(pipeline-memory-recall — MemoryHit 변경 후 회상 e2e) 통과.
- 세션 화면 Playwright 기능 검증: 탭 2개·목록 20행·드로어·라이브 필터 + 스크린샷 육안.
- DB 재측정: 고아 0·status 분포 active/completed만·324 잔존 grep 0.
- codex 적대 리뷰 → 잔존 3곳 발견·봉합.

관련: [[probe-deeper-before-concluding]] · [[whole-fix-over-minimal-patch]] · [[use-codex-for-adversarial-verification]] · [[measurement-pollutes-target|회고 296]] · 스펙 303(데모 시드 제거)·323(원형 사례)
