# 067 — A2A 노출 게이트: "겉도는 죽은 상태"는 소비층 fail-closed만으론 못 막는다

스펙: [083](../../docs/spec/083-a2a-expose-gate-to-ui-source.md)
사용자 보고: **"등록된 원격 에이전트를 A2A로 오픈하는 것은 이상함."**

## 무슨 일이었나

`exposed.a2a=True`는 *로컬(source=ui)* 에이전트를 우리 A2A 서버로 여는 플래그다(스펙 061). A2A 서버
게이트(`a2a_server._load_exposed_ui_agent`)는 이미 `source==ui`로 **fail-closed** — non-ui면 404다. 즉
보안·동작상으로는 이미 닫혀 있었다. **그런데도 사용자는 "이상함"을 봤다.** 왜? 플래그를 *쓰는* 층들이
같은 술어를 안 봤기 때문:

- `expose_agent`(입구)가 source 무관하게 True를 저장 → code/external에 True가 박혀도 서버는 404
- code/external 드로어가 "A2A로 공개" 토글을 무조건 렌더 → 원격 에이전트에 *불가능한 액션*을 제시
- `seed.py`의 Doc Translator가 `exposed={"a2a": True}`로 시드 → 데이터 자체가 불변식 위반
- 테이블 "공개" 컬럼이 모든 행에 Switch

= **"겉도는 죽은 상태"(dead state)**: 플래그는 켜졌으나 소비층이 무시해 *아무 일도 안 일어나는데*, UI는
켤 수 있다고 말한다. 보안 결함이 아니라 **데이터 정합·UX 결함**이라 happy-path 테스트·보안 검증에
안 걸리고, 사용자가 "이상함"으로 먼저 짚는다.

## 무엇을 했나

소비층 게이트(`source != "ui"`)와 *같은 술어*를 모든 쓰기·렌더 입구에 정렬:
입구 400 거부(끄기는 멱등 허용)·UI 토글 source=ui만·테이블 non-ui `—`·배지 `source==='ui' && a2a`·
seed False·기존 DB stale을 마이그레이션으로 청소. 불변식 `exposed.a2a==True ⟹ source=="ui"`를
데이터·코드 양쪽에 성립시켰다.

## 무엇이 빗나갔나 (적대 codex)

자가 검증(verify_083 8건 + 브라우저 3건)은 다 초록이었는데 codex가 **P1 2건**을 더 짚었다:
`expose_agent`도 마이그레이션도 `exposed`를 **JSONB 통째 교체**(`{"a2a": ...}` / `'{"a2a":false}'::jsonb`)해
형제 키를 파괴한다. 오늘 `exposed`는 a2a 단일 키뿐이라 *실제* 손실은 0이지만, "오늘 단일 키"는 내일
깨질 가정이고 1줄로 안전해진다 → merge(`{**(agent.exposed or {}), ...}`) / `jsonb_set(.., true)`로 하드닝하고
**G5·M4**(형제 키 보존)로 회귀를 잠갔다. 자가 초록은 *상상한 실패*만 본다 —
[[adversarial-review-before-destructive-ship]]가 다시 적중.

## 배운 것 → [learning 086](../learning/086-fail-closed-at-the-consumer-still-leaks-dead-state-align-the-predicate-at-every-writer.md)

소비층 한 곳을 fail-closed로 닫아도, 플래그를 *쓰는/그리는* 모든 입구가 같은 술어를 공유하지 않으면
"죽은 상태"가 쌓이고 UI가 불가능한 액션을 제시한다. 게이트는 *소비*가 아니라 *모든 쓰기 경계*에서
같은 술어로 정렬돼야 한다.
