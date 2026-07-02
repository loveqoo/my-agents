# 121 — 삭제/이름변경 참조 가드를 활성-only로 완화 (버그1)

## 배경 / 왜

사용자 버그 보고: RAG 컬렉션을 삭제하려는데 **에이전트의 과거 버전이 한 번만 참조해도 삭제 불가**.
`references.py`의 `agents_referencing`가 스펙 093에서 **의도적으로** 활성 config뿐 아니라 **모든 버전
(draft·active·archived)**을 훑기 때문(archived도 롤백 가능→dead ref 방지). 그러나 실사용에선 과도하게
엄격 — 오래 전 버전에 남은 참조가 자원을 영구히 못 지우게 한다.

사용자 결정: **활성(서빙) config만 차단, 과거 버전은 무시**. 트레이드오프(오래된 버전으로 롤백 시 그
자원 없이 동작)는 수용 — 런타임은 이미 dangling name을 경고 후 **우아하게 degrade**(그 도구/RAG 없이
동작, chat.py 미해석 warning). 이 완화는 `references.py` 주석이 스스로 지적한 **"usedBy 배지(활성만) ↔
버전 차단" 불일치도 해소**한다(배지는 활성만 세는데 삭제만 버전까지 세던 어긋남).

## 설계

- `agents_referencing(session, field, name)` — **활성 `Agent.config`만** 검사. 버전 스캔(`selectinload
  (Agent.versions)` + 버전 루프) 제거. 반환 `where`는 항상 `"active"`. 단일 함수라 **RAG 삭제·MCP 삭제·
  MCP 이름변경 셋 다** 자동으로 활성-only가 된다(일관·드리프트 0).
- `referenced_message`는 그대로(모든 ref가 active라 "(활성)" 라벨만 붙음 — 무해).
- 주석 갱신: references.py의 "참조 범위 = 활성 ∪ 모든 버전" 서술 → "활성 서빙 config만"으로. 완화 이유·
  트레이드오프(롤백 시 graceful degrade) 명시. blocks.py의 "비-archived 버전까지 센다" 주석도 갱신.

## 검증

- **단위(verify_093 갱신)**: T1/T5 활성 참조 → 여전히 409(차단). **T2(draft 버전)·T3(archived 버전) →
  이제 삭제 허용**(refs 빈 목록)으로 assertion 반전. referenced_message 포맷 테스트는 유지.
- **무회귀**: 활성 참조 차단은 그대로(주 목적 보존). RAG/MCP 삭제 라우트 무회귀.
- **적대(codex rung 3)**: 활성 참조가 새어 삭제되나·이름변경 가드도 함께 완화됐나·정상 모양 아닌 config
  fail-safe 유지 등 여집합.

## 비목표 (OUT)

- 과거 버전 config에서 삭제된 이름을 스트립(정리) — 사용자가 "무시" 선택(정리 아님). 롤백 시 graceful
  degrade로 충분. 필요 시 후속.
- 강제 삭제 버튼 — 이제 활성만 막으므로 불필요.
- 런타임 dangling 처리 변경 — 이미 경고+degrade(변경 없음).
