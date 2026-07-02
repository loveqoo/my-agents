# 099 — 관측·측정 계층 Langfuse (스펙 118)

## 무엇을

기술스택엔 있으나 코드 0줄이던 Langfuse 관측을 **inert-until-configured**로 배선. 방향 2(4개 방향 "모두
차례대로") 2번. 수치 기반 자율(방향 3 평가 하네스)의 토대.

## 어떻게

- `observability.py`: is_configured(키 둘 다)·trace_callbacks(미설정 []·graceful)·with_trace(config 비파괴
  병합, session/user 표준 키). chat.py 3곳 배선(메인 astream·재개 ainvoke·로컬 A2A 서빙). langfuse v4
  의존성 추가(키가 스위치).

## 잘된 것

- **부가물 3겹 접기**(learning 118 ①): 설정 게이트+graceful+비파괴 병합으로 관측이 채팅을 절대 안 깨게.
  키 없으면 완전 무동작, 있으면 자동 활성. 비밀은 env만 읽고 값 미노출.
- **전달 관통 검증**(118 ④): trace_callbacks가 리스트 돌려주는 것과 콜백이 실제 astream에서 이벤트 받는
  것은 다름 → Recorder 콜백으로 on_chain_start 수신 실측(실 Langfuse 서버 불요). 미설정 무회귀도 함께.
- **codex가 헬퍼 보장의 타입 구멍을 잡음**([P2] with_trace가 callbacks를 list로만 가정 — None·CallbackManager면
  TypeError). 현 배선 3곳은 callbacks 미주입이라 미재현이나, **헬퍼 보장 범위는 받아들이는 타입 계약
  전체**(118 ②)라 타입별로 접어 봉합+U4b 회귀가드. codex가 thread_id 보존·콜백 metadata 전달도 실측 확인.

## 배운 것 / 함정

- **부가 계층은 inert-until-configured + graceful + 비파괴 병합**(118 ①) — 상시 배선해도 안전.
- **헬퍼 무예외 보장은 파라미터 타입 계약 전체에**(118 ②) — "지금 안 터짐" ≠ "보장함".
- **config 병합은 프레임워크 예약 키(thread_id) 보존 실측**(118 ③).
- **외부 계측은 콜백이 실행에 꽂히는지까지**(118 ④, 리스트 반환 아님).

## 검증 생략 / OUT

- 실 Langfuse 서버 전송(CI 외부 비밀 불포함)·수동 span/score(방향 3)·대시보드(Langfuse UI)·OTel 범용.

→ learning 118
