# 365 — 페르소나 → 프롬프트 완전 개명 (테이블·API·config 키·라벨)

## 왜 (사용자 지시)

재사용 블록을 "페르소나"라 부르는데, 이미 코드가 "프롬프트"로 기울어 불일치다: 블록 body는 노드 카드·
오버라이드에서 `PromptField`(라벨 '프롬프트'·'시스템 프롬프트')에 들어가는데(스펙 274) 블록 자체만
"페르소나"로 남았다("같은 개념≠같은 컴포넌트"가 아니라 그냥 개념 이름이 갈렸다). 사용자 결정: **완전
개명**(라벨+테이블+API+백엔드 코드+config 키). 깊이 선택 = "완전(config 키까지, 저장 데이터 마이그레이션)".

## 범위 (측정: 백엔드 ~250·프론트 ~139·config.persona 키 88곳)

### 개명 대상 (persona → prompt / 페르소나 → 프롬프트)
- **DB**: 테이블 `personas`→`prompts`, 컬럼 `agents.persona`(해석 본문)→`agents.prompt`. 모델 `Persona`→`Prompt`.
- **config 키(JSONB)**: `config["persona"]`→`config["prompt"]` — `agents.config`·`agent_versions.config`
  전 행 데이터 마이그레이션(키 rename, 값 보존). 코드도 `cfg["prompt"]`로 읽게.
- **API**: `/personas*`→`/prompts*`(CRUD·apply·usage). 프론트 `api.ts` 호출 경로.
- **스키마**: `PersonaOut/In/ApplyOut/UsageAgentOut`→`Prompt*`.
- **백엔드 코드**: 변수·함수·주석의 persona→prompt(ctx["persona"]→ctx["prompt"] 등). seed·eval_suggest·
  references·serializers·card_builder·chat_context·chat 등.
- **프론트**: 식별자 persona→prompt, 라벨 '페르소나'→'프롬프트'(38 라벨), `PersonaStaleNote.tsx`→
  `PromptStaleNote.tsx`, mockData·types.
- **스펙 364 정합**: chat_context의 `cfg.get("persona")`(프롬프트 출처 해석)도 `cfg.get("prompt")`로.

### 개명 **금지**(이미 "prompt"이거나 다른 개념 — 충돌·오손 방지)
- `systemPrompt`(오버라이드 키·'시스템 프롬프트' 라벨) — 그대로. 별개 개념(자유 텍스트 오버라이드).
- 스펙 364가 방금 넣은 `promptSnapshot`·`prompt_id`·`prompt_name`·`promptRef`·`sentMessages` — 그대로(이미 prompt).
- `PromptField`/`PromptFields.tsx`(스펙 274 텍스트 컨트롤) — 그대로(이미 prompt, 개명 결과와 정합).
- 일반 단어 "prompt"(전송 프롬프트 등) — 개명 대상 아님.

## 마이그레이션 (구조만 — DB 초기화로 데이터 무시, 프로그램적 생성/learning 364)

**사용자 결정(2026-07-15): DB 초기화 예정 → 저장 데이터 마이그레이션 불필요.** 새 시드가 `config.prompt`·
`prompts` 테이블로 바로 쓰므로 JSONB 키 변환·데이터 보존 로직을 두지 않는다. 마이그레이션은 **스키마
구조만** — 초기화 후 처녀 빌드가 전 체인(초기: personas 생성 → 이 리비전: prompts로 rename)으로 정합
스키마를 만든다(append-only 유지 — 과거 마이그레이션 편집 금지):
1. `ALTER TABLE personas RENAME TO prompts` + 인덱스/제약 이름 정리.
2. `ALTER TABLE agents RENAME COLUMN persona TO prompt`.
- down: 역방향(prompts→personas·prompt→persona) 대칭. 손수 리비전 id 금지(프로그램적 생성=랜덤 hex).
- **초기화 후 실측**: 처녀 빌드가 clean boot·시드 성공, 테이블 prompts 존재·personas 부재·agents.prompt 컬럼.
- JSONB config 마이그레이션은 **OUT**(데이터 무시). 단 코드는 `cfg["prompt"]`를 읽고 seed는 `prompt` 키로 쓴다.

## 실행 순서 (안전)

1. 백엔드 모델·코드·API·스키마 개명(코드가 `prompt`/`prompts` 읽게) — **fast-worker 위임**(대량 기계 치환,
   금지 목록 엄수·전후 카운트 측정). 메인이 모델/마이그레이션/충돌 지점 검증.
2. 마이그레이션 생성·적용(데이터가 `prompt` 키·prompts 테이블로).
3. API 재기동(새 코드 로드).
4. 프론트 개명(식별자·라벨·파일명·api.ts) — fast-worker 위임.
5. 검증.

> 코드(prompt 읽기)와 데이터(prompt 키)는 **함께** 배포돼야 한다 — 마이그레이션 적용 후 재기동(learning 364).
> 전환 폴백(persona||prompt)은 두지 않는다(완전 개명·whole-fix). 단 마이그레이션 전 구 데이터로 부팅하지
> 않도록 순서 엄수.

## 완료 조건 (수치)

- **C1** 코드베이스에 개명 대상 잔여 0: `grep -rn "persona\|Persona\|페르소나"`가 **금지 목록(systemPrompt·
  promptSnapshot 등)과 무관한 잔여 0**(허용 잔여는 명시 열거). 프론트 '페르소나' 라벨 0.
- **C2** 마이그레이션 실측: `prompts` 테이블 존재·`personas` 부재·`agents.prompt` 컬럼·config 표본 persona 키 0.
- **C3** 기능 무회귀: `make test` SUITE_OK, 실채팅(프롬프트 참조 해석·회상·스펙 364 promptSnapshot 정상),
  프롬프트 CRUD(생성·수정·적용·삭제) 왕복, 에이전트 폼에서 프롬프트 참조 저장·해석.
- **C4** tsc 0. 브라우저: 빌딩블록 '프롬프트' 목록·에이전트 폼 '프롬프트' 라벨·다해상도 깨짐 0.
- **C5** 스펙 364 정합 유지: turn 저장 시 prompt_id/name·promptSnapshot이 새 config.prompt 경로로도 정확.

## 검증 결과 (2026-07-15 실측 — done)

- **C1** 코드 잔재 0: `grep persona|페르소나`(packages·admin/src·tests, personal·alembic히스토리 제외) = **0**.
  초기 sweep에서 두 곳이 늦게 드러나 봉합 — (a) `tests/e2e/specs/*.ts`가 개명된 `/prompts` 대신 `/personas`
  호출(make test 밖·tsc 밖이라 초록에 안 걸림), (b) `scenarios.md` 생성 플로우 스텝의 "페르소나 선택".
  둘 다 개명. **허용 잔재(명시)**: `tests/browser/scenarios.md` 3곳=테스터 아키타입(다른 개념·유지),
  마이그레이션 히스토리(append-only), `docs/spec/CLAUDE.md`·`docs/guide/*`(인간 영역 도메인·가이드 — **후속**).
- **C2** 스키마 실측: 초기화 후 처녀 빌드 clean boot·시드 성공, `prompts` 존재·`personas` 부재·`agents.prompt`
  컬럼·config 표본 `persona` 키 0·`prompt` 키 5.
- **C3** `make test` SUITE_OK, `verify_364` ALL PASS(프롬프트 참조 해석·회상·promptSnapshot·오버라이드 정상).
- **C4** tsc 0. 브라우저: 빌딩블록 탭 "프롬프트 7"·에이전트 폼 `Field label="프롬프트"`(데스크톱 1440·좁은 420
  둘 다 프롬프트 표시·페르소나 0·레이아웃 정상, shot-365-form-desktop/narrow).
- **C5** verify_364로 config.prompt 경로에서 prompt_id/name·promptSnapshot 정확 확인.

## 후속 (인간 영역 — 승인 필요)

- **가이드 개명**: `docs/guide/nocode-agent-guide.md`(5곳 "페르소나")→ `build-html.py` 재빌드로
  `admin/public/guide/index.html` 갱신 + `guide-blocks.png` 스크린샷 재촬영(구 "페르소나" 탭 노출 중).
- **도메인 문서**: `docs/spec/CLAUDE.md`의 "페르소나 (역할…)" 개념 서술 1곳.

## OUT

- 턴 분석 UI(스펙 364 OUT 유지) — 별개.
- `systemPrompt` 오버라이드 키 개명 — 안 함(별개 개념).
