# 101 — 스토어를 직접 시드하는 테스트는 write-schema 드리프트를 못 잡는다 / 리뷰어도 검증하라

관련: learning 100(채널 격리·인가 입도), verification-ladder-three-rungs(메모리), probe-deeper(메모리)

## 1. 직접 시드 = write-schema 층을 우회 → 지속 드리프트가 숨는다

**증상.** 능력 브로커의 allowlist는 `AgentConfig.config["capabilities"]`에서 온다. 단위·그래프 레벨
테스트(allowlist를 `lambda k:True`/시드 행으로 직접 주입)는 전부 초록. 그런데 풀 HTTP 경로에선 브로커가
아무것도 발견 못 함. 원인 = `AgentConfig` Pydantic 모델에 `capabilities` 필드가 없어
`body.config.model_dump()`가 그 키를 **조용히 드롭** → 저장 config에 allowlist가 없음 →
`chat.py`가 읽어도 `[]`(deny-by-default).

**왜 안 잡혔나.** verify_100의 HTTP 하네스마저 Agent 행을 `SessionLocal`로 **DB에 직접 시드**했다.
직접 시드는 create-엔드포인트의 **write-schema(Pydantic)를 우회**하므로, 스키마가 필드를 드롭해도
테스트 픽스처엔 그 필드가 그대로 있다 — 지속 경로가 끊긴 걸 픽스처가 **가려버린다**.

**교훈.** *지속(persistence)을 검증하려면 실 write-schema/create 경로를 타야 한다 — 테이블을 직접
시드하지 마라.* 직접 시드는 read 경로만 검증하고 write-schema의 필드 드롭·검증·변환을 통째로 건너뛴다.
통합 rung의 고유 가치(seed/glue drift 포착)는 "실 인프라"만으로 부족하고 **"실 입력 스키마"**까지 타야
완성된다. 새 검증 설계 첫 질문: *"이 픽스처는 프로덕션이 쓰는 그 write 경로로 데이터를 넣는가, 아니면
스토어에 밀어넣어 그 층을 건너뛰는가?"*

## 2. 스테일 --reload = 같은 테스트가 두 코드베이스를 검증(split-brain)

`--reload` 개발 서버가 이전 세션 편집을 안 물으면(또는 중간 import 에러로 구 코드 유지) **in-process
테스트는 신 코드, HTTP 테스트는 구 코드**를 검증한다. 같은 로직인데 경로에 따라 다른 결과.

**진단은 추측이 아니라 로그의 *부재*로.** "chat 요청 중 `/_remote/mcp/` 호출이 0" = 서버가 MCP
discovery를 **시도조차 안 함** → 서버 코드가 그 경로를 모른다(구 코드). *기대한 활동의 부재*가
"어느 코드가 도는지"를 가른다. 고침 = 서버 재기동(사용자 원격이면 호스트 로컬 작업 직접).
**규칙: HTTP/통합 테스트가 같은 로직의 in-process 테스트와 불일치하면, 로직을 의심하기 전에 서버가
스테일 코드를 도는지 의심하라** — 로그 활동으로 확인 후 재기동, 그 다음에 남는 실패가 진짜 결함.

## 3. 리뷰어도 검증하라 — 알려진 불변식을 뒤집는 P1은 라인 직독으로 확인

codex가 `[P1] untrusted 출력이 SystemMessage에 삽입`을 `orchestrate.py:104-117`로 인용했으나 그건
`describe()`였다 — 실제 `build_synthesis_messages`(81-100)는 delegated를 **HumanMessage**(데이터
채널)에 넣는다. 채널 격리(learning 100)는 이미 있고 verify_100이 단위 단언한다. **오탐.**

**교훈.** 자가검증 대신 타자(codex) 검증을 우선하되(운영 매뉴얼), *타자도 무오류가 아니다*. **이미
고쳐둔/단언된 불변식을 정면으로 뒤집는 P1은 수용 전에 소스 라인을 직접 대조**하라 — codex의 라인 인용은
틀릴 수 있다(인접 함수를 가리키는 오프바이). "probe deeper before concluding"의 리뷰어판: 리뷰 결과가
내 측정(단위 단언)과 어긋나면 리뷰를 의심하고 한 겹 더 판다.

(learning 100의 "codex 설계한계 = 제3의 판정[명시화]"는 이번에도 재적용 — codex #1/#2가 이미 스펙 100
§6에 수용·문서화된 입도 한계를 재발견. 답은 fix도 dismiss도 아닌 *이미 문서화된 경계 지목*.)
