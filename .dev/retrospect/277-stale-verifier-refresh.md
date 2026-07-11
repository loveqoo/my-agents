# 277 — stale verifier 정리 + artifact 노드 config 주입 회귀 수정 (스펙 302)

## 무엇을 했나
dedup 연작 내내 backlog에 쌓인 6개 "stale verifier"를 deep-reasoner 전수 진단 후 수선. **6개 중 1개(190)는
stale가 아니라 진짜 프로덕션 회귀**였고, 5개는 픽스처/테스트데이터 드리프트.

## 배운 것 / 복리 포인트

- **"stale verifier"라 미룬 것 중에 실 프로덕션 버그가 숨어 있었다**(190). langgraph 1.2.5가 config 주입을
  애노테이션 **문자열 매칭**으로 판정하는데, `from __future__ import annotations`로 문자열화된 PEP 604
  `"RunnableConfig | None"`이 허용집합에 없어 config 미주입→artifact 계열 에이전트(ConfigDriven·SlotFill·
  Targeting) 첫 노드 크래시. **스위트가 artifact를 안 태워 미검출** — verify_190만이 잡고 있었다. 교훈:
  **실패하는 verifier를 "낡았겠지"로 뭉개 backlog에 방치하면 그 뒤의 실 회귀를 못 본다.** stale 판정도
  전수 진단으로. → [[verification-ladder-three-rungs]] [[installed-guard-isnt-covering-guard]]

- **`= None` 기본값은 이 버그의 눈속임 수선**. `config: RunnableConfig | None = None`으로 고치면 크래시는
  멎지만 애노테이션이 여전히 미인식→config 미주입→기본값 None→`thread_id=""`→스텝로그 리플레이 캐시
  (멀티턴 interrupt 결정성) **무력화**. happy-path 초록·리플레이만 조용히 깨짐. 반드시 **애노테이션을
  인식형(`RunnableConfig`)으로** 바꿔 실제 주입을 복원해야 한다. deep-reasoner가 langgraph
  `RunnableCallable`로 `"RunnableConfig | None"→주입X`, `"RunnableConfig"→주입O`를 실증. → [[cap-the-raw-source-not-the-buffer]] 계열(눈속임 초록 경계).

- **연쇄 드리프트는 앞 크래시가 뒤를 가린다**(131 = 4단 드리프트). `rag:Obsidian` 부재 크래시를 고치니
  `FakeProv.approval_for` 인자 부족, 그걸 고치니 `fake_search` 인자 부족, 그걸 고치니 V3 화이트리스트 단언.
  **한 verifier의 첫 실패만 보고 "1곳 고치면 됨"이라 단정 금지** — 실행이 진행되며 그동안 미도달이던
  하위 단언들의 누적 드리프트가 순차로 드러난다. 재실행-수선을 dry될 때까지 반복. → [[probe-deeper-before-concluding]]

- **fake mock은 실 시그니처를 흉내내되 "extra kwargs 흡수"가 안전**. 084 FakeMem.search가 실 mem0의
  `threshold` kwarg(스펙 158)를 안 받아 TypeError→빈 회상. mem0 search는 extra kwargs 허용이므로
  `**_kw` 흡수가 정본. 실 계약이 파라미터를 늘리면 mock이 조용히 깨진다(시그니처가 곧 계약). → [[monkeypatch-seam-contract]]

- **몽키패치는 "정의 모듈"이 아니라 "lookup 지점"을 패치**(084). 스펙 291 분해로 `resolve_agent_mem_cfg`
  호출이 `api.agents.memory_routes` 모듈 글로벌로 이동했는데 테스트는 `api.agents`를 패치→가로채기 실패→
  진짜 함수 실행. 심볼이 재수출돼도 **실제 이름 조회가 일어나는 모듈**을 패치해야 한다. → [[monkeypatch-seam-contract]]

- **stale 판정 = 픽스처 vs 프로덕션 분리 후 착수**. deep-reasoner가 6개를 "프로덕션 1(190) / 순수 픽스처 5"로
  분리하고 프로덕션을 최우선 착수 권고. 픽스처 수정은 검증 의도 불변이 조건(100 active_version=None로 ui
  배제 유지 등 — 아무 값이나 넣으면 판정 왜곡).

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(190 애노테이션 mypy·부팅). 6개 verifier 전부 PASS.
- **실인프라 통합**: verify_190이 artifact 그래프 직접 호출로 config 주입 복원 실증. 스위트 51/51(실패 0, 광역 무회귀).
- **적대(codex)**: 190이 실제 주입 복원인지 `=None` 눈속임 아닌지·리플레이 결정성 보존·서브클래스 부작용 →
  **"여집합 공격 실패 — 결함 없음"**. non-optional이라 미인식 시 조용한 None 아닌 즉시 TypeError(눈속임
  불가)·langgraph `ensure_config`로 `(config or {})` 안전·thread_id 경로 복원·codex가 verify_188·190 실행
  통과 확인.

## 남은 것 / 주의
- **dev 서버 재기동 필요**: api 서버 `--reload`는 packages/agent를 안 watch → 190 수정이 실행 중 서버에
  자동 반영 안 됨. artifact 에이전트를 서버로 쓰려면 재기동 필요(커밋 코드엔 반영됨).
- 배경 verifier 폴 타임아웃(10초) 격리 실행 문서화(회고 276). eval_* 내부 잔여 중복 미전수.
