# 010 — 비밀값 암호화 저장 (모델 api_key · 코드 에이전트 token)

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [008 모델 레지스트리](./008-model-registry.md), [009 코드 에이전트 원격](./009-code-agent-remote-exec.md)

> 단순 에이전트 실행·구성의 핵심 비밀은 **모델 `api_key`**(LLM 호출 키)다. 지금은 DB 평문 저장
> (출력만 마스킹)이라 위험. 비밀값을 **at-rest 암호화**하고, 런타임에서만 복호화해 사용한다.

## 1. 목표 / 비범위
### 목표
- `models.api_key`, `agents.token`(코드 에이전트)을 **Fernet 대칭키로 암호화 저장**.
- API 출력은 **고정 마스킹 표시**(평문/암호문 미노출). 편집 시 마스킹 값이면 보존.
- 런타임에서만 복호화: chat.py가 모델 키/토큰을 복호화해 build_agent·mem0·원격 Authorization에 사용.
- 키 관리: `APP_SECRET_KEY`(env) → 없으면 `.dev/.secret_key`(생성·영속, gitignore). 개발 즉시 동작 + 키는 코드/DB 밖.
- 부수효과: 코드 에이전트 토큰을 실값 암호화 저장 → 원격 인증 실제화 가능(마스킹으로 못 하던 것).

### 비범위
- KMS/HSM·키 로테이션 자동화·봉투암호화 — 추후(파일/env 키로 충분히 시작).
- 스키마 변경: api_key(String400)/token(String200)에 Fernet 토큰이 들어감(여유). 마이그레이션 불필요.

## 2. 설계
- `crypto.py`: `encrypt(s)->str`, `decrypt(s)->str`(InvalidToken이면 **레거시 평문으로 간주해 그대로 반환** — 무중단 이행), `SECRET_MASK` 상수.
- 쓰기: model/agent 생성·수정 시 평문 키가 오면 `encrypt`. 마스킹 표시가 오면 보존.
- 출력: `serializers`가 비밀 존재 시 `SECRET_MASK`만 반환(부분 평문 노출도 제거).
- 런타임: `chat.py`가 `decrypt` 후 사용. 원격 토큰도 복호화해 `Authorization: Bearer`.
- 시드: MLX 키·데모 토큰을 암호화 저장.

## 3. 검증 (결과)
- [x] DB는 Fernet 암호문(`gAAAAA...`), 응답은 `••••••••`만 — 평문 비노출 확인.
- [x] 단순 에이전트 실행: 암호화된 모델 키 복호화 → LLM 호출 정상.
- [x] 모델 수정: 마스킹 재전송→보존, 빈문자열→제거, 새 평문→암호화 교체.
- [x] mem0(복호화 임베더 키)·코드 에이전트 원격(복호화 Bearer) 정상.
- [x] 전체 E2E 27 passed. codex GATE — **P1 2건 수정**(키 불일치 시 암호문 누출 방지: Fernet 형태면 에러; 원격 에러 본문 클라 비전송) + P2 1건(키 제거 의미 구분). 학습 [[014]].
- [x] `.dev/.secret_key` gitignored.

## 추후
- KMS/봉투암호화, 키 로테이션, 감사 로그.
