# 010 — mem0 벡터 스토어 pgvector 이전 회고

날짜: 2026-06-24
브랜치: `feat/agent-service` (main 머지·push 금지 — 사용자가 직접 테스트)
지배 스펙: [019](../../docs/spec/019-mem0-pgvector-shared-backend.md)
이전 회고: [009-memory-user-scoping](./009-memory-user-scoping.md)

## 루프 개요
"메모리 테스트·로직 검증"으로 시작했으나, 테스트 직전 **사용자가 아키텍처 우려를 제기**(파일 기반
DB는 N-인스턴스에서 깨진다) → 작업이 "pgvector 공유 백엔드 이전"으로 재정의됨. 이전 후 스코핑까지
한 번에 검증. 또 사용자가 **임베딩 차원 불일치 위험**을 지적해 하드코딩을 하드닝.

## 무엇이 잘됐나
- **사용자 우려를 추측 없이 코드로 검증**: "파일 기반이 문제" → mem0 지원 백엔드 24종을 설치 소스로
  확인해 pgvector 발견, 히스토리 DB가 회상 경로 밖임을 `Memory.search` 소스로 입증, 실제 임베딩
  차원을 라이브 서버 probe로 1024 확인. "추측 말고 동일 사례 확인" 표준 제약을 전 구간 준수.
- **이미 있는 스택에서 해답을 찾음**: 새 인프라(qdrant 서버)를 들이는 대신 **이미 돌던 PostgreSQL**을
  재사용. 오히려 기존 compose가 `postgres:16`(pgvector 없음)이라 루트 스펙 의도와 어긋나 있던 걸 정정.
- **타자 검증이 또 P1을 잡음**: 내가 짠 DATABASE_URL 분해 로직의 happy path는 통과했지만, 서브에이전트가
  "mem0가 내부에서 URL을 재조립한다"는 구조를 들춰 자격정보 부재 'None' 인증·특수문자 오파싱(P1 2건)을
  발견 → `connection_string` 위임으로 근본 수정. 자가검증이었으면 못 봤다. ([[009-memory-user-scoping]]에
  이어 두 번째 "타자 검증이 happy-path 뒤의 결함을 잡은" 사례.)
- **end-to-end 실측으로 닫음**: 테이블 생성·차원·스코프 격리·N-인스턴스 공유·엣지케이스 4종을 전부
  실제 mem0+Postgres로 돌려 확인(서버가 떠 있어 가능했음). 정적 검증에 머물지 않음.

## 무엇이 잘못됐나 / 배운 것
- **초안의 분해 방식이 취약**: URL을 host/user/password로 분해→mem0가 재조립하는 왕복을 처음엔 못 봤다.
  외부 라이브러리에 연결정보를 넘길 때 **그 라이브러리가 내부에서 무엇으로 변환하는지**를 먼저 봤어야
  했다(009에서도 "외부 SDK 제약은 Context에서 선확인"이라 적어놓고 또 실행 중에 발견). → 학습 [[020-pgvector-shared-backend-and-dsn-delegation]].
- **차원 하드코딩을 사용자가 먼저 지적**: `_EMBED_DIMS=1024`가 모델과 분리된 가정임을 내가 먼저 플래그했어야.
  pgvector는 생성 시 차원 고정이라 모델 교체 시 조용히 죽는 함정(018 공백 함정과 동형).
- **공유 DB에 테스트 데이터 오염**: 검증하느라 실 `agents` DB의 mem0 테이블에 alice/bob을 넣었다가
  TRUNCATE로 정리. 다음엔 검증용 임시 스코프·정리를 처음부터 설계.

## 다음에 다르게 / 추후
- 외부 라이브러리에 **연결문자열/자격정보**를 넘길 땐 분해 대신 **원본 위임**을 먼저 고려(표준 파서에 맡김).
- 차원 같은 **모델 결합 상수**는 동적 도출(probe/레지스트리 컬럼)을 추후 과제로(스펙 019 범위 밖).
- 미완: 임베딩 서버 다운 시 graceful 무력화 dry-run(사용자 브랜치 테스트), 히스토리 DB 공유.

## 관련 기록
- 학습 [[020-pgvector-shared-backend-and-dsn-delegation]] · [[019-mem0-memory-scoping]]
- 스펙 [019](../../docs/spec/019-mem0-pgvector-shared-backend.md) · 회고 [[009-memory-user-scoping]]
