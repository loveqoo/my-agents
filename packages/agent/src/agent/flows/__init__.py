"""생성된 커스텀 에이전트 플로우 (스펙 099).

`agent-flow` 스킬이 저작하는 실사용 `CustomAgent` 구현이 사는 곳. `examples/`(default·plan_execute)는
인터페이스 *참조* 2종만 유지하고, 스킬 산출물은 여기에 둔다(관심사 분리).

각 플로우는 `runtime._bootstrap_builtins()`에 late-import + `register_agent("<key>", <Cls>)` 두 줄로
**신뢰 등록**된다 — 런타임 eval/import 경로 없음(스펙 085 §보안경계 보존).
"""
