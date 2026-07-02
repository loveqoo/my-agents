# 118 — 부가 계층은 inert-until-configured / 헬퍼 보장은 받아들이는 타입 계약 전체를 덮어야

스펙 118(관측 계층 Langfuse)에서 배운 것.

## 1. 부가물(관측·계측)은 설정될 때만 켜지고, 실패해도 핵심 경로를 안 깬다

관측은 **부가물이지 하중이 아니다**. 켜져 있든 없든 핵심 경로(채팅)가 관측 때문에 깨지면 실패다. 그래서
세 겹으로 접는다: ①**설정 게이트** — 필요한 env(키 **둘 다**)가 있을 때만 활성, 없으면 no-op([]),
②**graceful** — 패키지 미설치·핸들러 생성 실패도 예외 없이 no-op(try/except로 import·생성 둘 다 감쌈),
③**병합 비파괴** — 실행 config에 얹되 기존 값(callbacks/metadata/configurable) 안 덮고 확장, 미설정이면
원본 그대로. "키가 스위치" — 패키지는 설치돼 있고 키를 넣는 순간 활성(추측 불가한 외부 비밀은 env로만
받고 값은 코드/로그/응답에 절대 안 남김). 이 패턴이면 부가 기능을 안전하게 상시 배선해둘 수 있다.

## 2. 헬퍼의 "보장"은 그 헬퍼가 **받아들이는 타입 계약 전체**에 대해 성립해야 한다 (codex P2)

`with_trace`가 "기존 callbacks 보존·확장, 예외 없음"을 보장한다며 `[*cfg.get("callbacks", []), *cbs]`로
짰는데 — 이는 callbacks가 **list일 때만** 안전하다. 그런데 받아들이는 타입(RunnableConfig.callbacks)은
`list | CallbackManager | None`이다. None·CallbackManager(비-iterable)가 오면 splat이 TypeError → 보장
파탄. **현재 호출처가 그 값을 안 넘긴다고 안전한 게 아니다** — 헬퍼의 보장 범위는 *호출처의 현재
습관*이 아니라 *파라미터의 타입 계약*이다. 타입별로 접어(None→[], list→extend, 그 외→wrap) 어떤
입력에도 안 던지게. "지금 안 터진다"와 "보장한다"는 다르다(learning 117 ⑤ "성립 범위" 계열).

## 3. config에 얹을 땐 프레임워크가 이미 쓰는 키(configurable.thread_id)를 보존했는지 실측

관측 콜백을 config에 병합하면서 `configurable`(재개 키 thread_id)을 드롭하면 HIL 재개가 깨진다. dict
확장으로 보존됨을 코드로 보장하고, **thread_id가 콜백 metadata로 실제 전달되는지**까지 최소 그래프로
실측(LangGraph가 configurable.thread_id를 콜백 metadata로 자동 forward — 확인). 얹기(merge)는 항상
"기존 것 보존 + 내 것 추가"이고, 그 보존을 조작적으로 검증.

## 4. 외부 서비스 계측은 "콜백이 실제 실행에 꽂히는가"까지 관통 검증(리스트 반환 아님)

`trace_callbacks()`가 리스트를 돌려주는 것과 그 콜백이 **실제 그래프 실행에서 이벤트를 받는 것**은 다르다.
Recorder 콜백을 `with_trace`로 주입해 astream을 돌리고 `on_chain_start` 수신을 단언 → 전달 관통 실측(실
Langfuse 서버 불요). 미설정 실행은 Recorder 미수신 + 정상 완주로 무회귀도 함께.

## 적용
- 부가 계층(관측·계측·플래그)은 설정 게이트 + graceful + 비파괴 병합 3겹으로 상시 배선해도 안전하게.
- 헬퍼의 무예외 보장은 파라미터의 **타입 계약 전체**에 대해(현 호출 습관 아님) — 비정상 입력 회귀가드.
- config 병합은 프레임워크 예약 키(thread_id 등) 보존을 조작적으로 검증.
- 외부 계측은 "콜백이 실행에 꽂혀 이벤트 받는가"까지(리스트 반환으로 만족 말 것).

관련: [[demonstrate-success-not-just-invocation]] · [[installed-guard-isnt-covering-guard]] ·
[[cap-the-raw-source-not-the-buffer]]
