# 284 — 에이전트 목록 재설계: 출처 탭 · 내 것 tint · 신호등 상태 (태그 계층 해소)

> 사용자 지시 6건(태그들의 계층이 어려움): ①기본 public+가시성 태그 제거, 내 것=행 배경 연한
> 그린/블루 ②출처 탭(Internal(UI)/Internal(Code)/External) — 소유 태그 소멸 기대 ③UI 탭에 에이전트
> 종류 표시 ④페르소나(컬럼) 제거 ⑤탭 안 검색(꼭 필요한 조건만) ⑥상태=신호등 자리(파랑/노랑/빨강).

## 범위 분할 (측정 근거)
- **①의 "기본 public"은 스펙 285로 분리**: 현 모델은 공개=owner_id 소멸(147/154)이라 "기본 public+
  내 것 tint"가 양립 불가(공개하면 생성자 소실). 가시성 축은 404-fold·복제 게이트·A2A 불변식·메모리
  게이트가 얽힌 보안 경계(147 codex High 봉합들) — 생성자 축 분리(마이그레이션)+RBAC 체크리스트+
  codex 적대가 필요한 별도 스펙. **284는 UI 전부**(가시성·소유 태그 제거, tint, 탭, 종류, 검색, 신호등).

## 변경 (AgentsView + shared DataTable)
1. **출처 탭**(antd Tabs — 데이터 집합 전환=Tabs 규칙): Internal (UI) / Internal (Code) / External.
   소스 필터 Select·소유 필터 Select 제거(탭+tint가 대체). 검색·상태 필터·정렬은 탭 아래(=탭 안).
2. **내 것 tint**: DataTable에 `rowStyle(row)` prop 신설(데탑 tr+모바일 카드 공통) — owner_id===meId
   행 배경 연한 그린. OwnerTag·가시성 표시 제거(가시성 전환은 상세 페이지에 유지 — 285 전까지 잔존).
3. **UI 탭 '종류' 컬럼**: typeLabel(283 단일 출처) Tag. Code/External 탭엔 무의미라 미표시.
4. **페르소나 컬럼 제거**(전 탭).
5. **탭 안 검색**: placeholder 탭별(UI=이름·종류·모델, Code=이름·모델·커밋, External=이름·모델).
   predicate에 commit 추가(Code), 종류(283) 유지.
6. **신호등 상태**: StatusPill(라벨) → 고정 슬롯의 색 점(●) + Tooltip(라벨·의미). 색=사용자 지정:
   파랑(온라인)/노랑(유휴)/빨강(오프라인).

## 완료 조건
1. 탭 3개·기본 Internal(UI), 탭 전환으로 소스별 목록(e2e). 소스/소유 Select 부재.
2. 내 것 행 tint(스타일 존재), 타인/공유 행 무색(e2e style 검사).
3. UI 탭에 종류 Tag(노드형 등), Code 탭엔 종류 컬럼 없음(e2e).
4. 페르소나 컬럼 부재(e2e). 5. 탭별 placeholder·검색 동작(283 무회귀 포함). 6. 상태 점+툴팁(e2e).
7. tsc 0 + 283 갱신 GREEN + 모바일 오버플로 0.

### 검증 결과
- **verify-284-agents-list.mjs 16/16 ALL GREEN** — 탭 3개·기본 UI·탭 분리, 소유/소스 Select 부재,
  페르소나 컬럼 부재, UI 탭 '종류' 컬럼·Tag(노드형), 내 것 행 tint(dt-row-tint 클래스), 가시성/소유
  태그 부재, 상태 점(aria-label)+툴팁, 탭별 placeholder.
- **tint 특이성 함정**: `.dt-antd-sub … expanded-row > td { background }` 기존 규칙이 tint를 덮어
  보조행만 흰 줄로 남음 → expanded-row.dt-row-tint 특이성 상향으로 본행+보조행 한 몸(육안 재확인).
- **형제 회귀**: 283(종류 검색)·276·274 GREEN. tsc 0·모바일(360px) 오버플로 0.
- '표시 안내' Popover를 새 범례(tint·신호등·예외 태그)로 갱신(구 태그 설명은 죽은 안내라 제거 —
  244 "죽은 라벨" 규율). codex 스킵(UI 표현·payload 무변경).

### 후속(tint 2색, 사용자 지시)
"내 것인데 private면 연한 레드로" — tint를 변형으로 확장: **red=내 것(비공개, 주의 — 나만 사용)**,
green=내 것(공개). 현 모델은 공개=owner 소멸이라 green은 285(생성자 축 분리) 이후 등장 — 지금은
내 것 전부가 red(정직: 전부 비공개 상태라는 사실의 노출). DataTable rowTint가 'green'|'red' 반환,
theme.css 2규칙, 범례 갱신. verify-284 red 클래스 단언 16/16 GREEN.

### 후속 2(사용자 지시 2건)
- tint red→**blue**(레드는 거부감): 내 것(비공개)=연한 파랑, 초록=공개(285 이후). 범례 동기화.
- **'비준수' 태그 소멸**: non_conforming은 code/external의 정상 상태(원격=다른 종류)라 그 탭 전 행에
  붙음=정보 0(사용자 지적). 예외 표시 원칙을 진짜 문제(설정 실패)로만 좁힘 — 범례에서도 제거.
  verify-284 blue 클래스 단언 16/16 GREEN.
