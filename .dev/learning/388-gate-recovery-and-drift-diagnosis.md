# 388 — 게이트 복구: "도구 드리프트" 진단도 버전 대조로 반증하고, MI는 응집 가족 이동으로 넘는다

## 맥락

스펙 383·384 검증 중 발견된 `make metrics` RED 4축(format 17·naming 17·complexity D2·MI B1)을
스펙 386으로 복구. 전 게이트 그린 + mypy 베이스라인(block_versions 2건)까지 소거해 0. 동작 불변은
codex AST-동일성 리뷰 + 실채팅 관통 + 씨앗 그물로 판정(실모델 suite는 환경 차단 — 모델 미등록).

## 교훈

- **"도구 버전 드리프트" 진단은 구버전 도구로 반증하라.** format 17파일을 "ruff 0.15.21이 새로
  잡는 것"이라 진단했는데, ruff@0.14.14로 돌려도 **동일 17개** — 도구가 아니라 `make format`을
  안 거치고 커밋된 파일들이었다(346~372 캠페인). 도구 탓 진단은 도구를 고정해 대조하기 전엔 가설.
- **게이트 RED의 누적은 "게이트를 안 돌린 커밋"의 청구서다.** 17개 파일·naming 17건·D 2곳이 전부
  이전 스펙들에서 metrics-fast를 안 돌리고 커밋된 잔재. 스펙 완료 전 `make metrics-fast` 한 번이면
  각각 그 자리에서 잡혔다 — 완료 조건에 게이트 실행을 포함할 것(스펙 291의 원래 취지).
- **MI(B→A)는 함수 다이어트가 아니라 응집 가족의 모듈 이동이 정석.** chat.py MI 18.77→20+에
  필요한 건 리팩터가 아니라 **이미 응집된 트레이스 가족 6함수를 정주지(chat_trace.py)로 이동**
  (외부 참조 0 확인 후 verbatim, 파사드 재수출 유지). 결과 24.70 — 파일 크기가 MI의 지배 변수일
  때 자르는 위치는 "가장 응집되고 참조가 닫힌 가족"이다.
- **verbatim 슬라이스는 앵커 단언부터**(회고 381 재확인) — 이동 스크립트의 라인 경계 단언이 한 줄
  오프(1128 vs 1129)를 잡아 잘못된 절단을 실행 전에 막았다. 단언 실패=파일 무변경으로 안전.
- **naming R1은 이분법이 아니라 판정이다** — bool 반환이라고 다 술어형 rename이 아니다. 부수효과+
  성공 bool(락 획득·리더 시도·이력 기록·스케줄 재적재)은 ACTION_WHITELIST에 **부수효과 실증+사유**로
  등재, 순수 판정(_eq·_pinned_by_*)만 rename. 화이트리스트는 면제 명부가 아니라 판정 기록.
- **mypy는 리팩터 중에도 그물이다(382 재현)** — 추출한 `_consolidate_one_user`의 union(dict|str)
  미협소화를 mypy가 즉시 잡음(`outcome["before"]`에 str 인덱싱 불가). isinstance 협소화로 봉합.
  베이스라인 2건(bare `type`의 폴리모픽 접근)도 `type[Any]` 명시로 소거 — 베이스라인은 안고 가는
  게 아니라 줄이는 것.

[tool-drift-needs-version-pinned-refutation, red-gates-are-unrun-gates-bill,
mi-crossed-by-cohesive-family-move, verbatim-slice-anchor-asserts, action-whitelist-is-judgment-record,
mypy-nets-refactor-unions]
