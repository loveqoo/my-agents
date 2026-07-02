# 111 — 능력 브로커: 메모리 수정/삭제 능력 (memedit)

## 배경 / 왜

브로커 메모리 능력은 **읽기**(104)·**저장(add)**(105)까지 왔다. 남은 것: **수정(update)/삭제(delete)**.
add(105)와 결정적으로 다른 점 — add는 *자기 스코프에 새 행 생성*이라 대상이 없지만, update/delete는
**기존 특정 mem_id를 대상**으로 하므로 "그 행이 정말 본인 것인지" **소유권 검증이 선행**돼야 한다
(learning 054·069). HTTP 라우트엔 이미 있다(`memory_routes.py` update/delete + `_assert_user_owns`);
이 스펙은 같은 방어를 **브로커 능력**으로 노출한다(단일 소유권 헬퍼 재사용 = 드리프트 0).

이건 **소유권 경계 스펙**이므로 `docs/spec/CLAUDE.md` RBAC 체크리스트가 자동 적용된다(아래 §RBAC).

## 설계

- **kind `memedit`, cap `memedit:user`** (memwrite=add와 분리 — 삭제는 비가역이라 승인 민감도가 다르다).
- **args**: `{"op": "update"|"delete", "mem_id": str, "text": str(update 전용)}`.
- **부수효과 → 승인 게이트 항상**(`approval_for` non-None, 105와 동일 구조). 승인 payload는 op+mem_id
  (+update 시 새 본문)을 마스킹 없이 노출 — "승인한 것 == 실행되는 것"(op·mem_id·text 일치).
- **소유권 술어 단일화**: `memory.user_owns(user_id, mem_id, mem_cfg) -> bool` 추출. `memory_routes.
  _assert_user_owns`(raise)와 브로커 invoke(InvokeResult error)가 **같은 술어**를 감싼다(드리프트 0).
- **invoke 순서**: op·mem_id 검증 → mem_cfg(백엔드 None이면 부수효과 0으로 error) → `user_owns` 확인
  (실패=미소유/부재 **동일 error 메시지**로 404-fold) → op=update `memory.update_memory` / delete
  `memory.delete_memory` → 확인 InvokeResult.
- **스코프=principal 도출 user_id 고정** — args의 user_id 등 무시(anti-leak 불변식, 104/105 동일).
  머신 principal(user_id None) → candidates 공집합(deny, DB 미접촉).
- **RBAC**: `capability:memedit` invoke. **member 시드 없음**(deny-by-default) — 삭제 비가역이라
  fail-closed(105 memwrite는 self_approve 시드했으나 삭제는 민감도 상향). admin/superuser만. member
  자기-편집 허용은 **의도적 정책 추가**(admin이 `member, capability:memedit, invoke` 부여)로 별도.

## RBAC/소유권 체크리스트 답변 (docs/spec/CLAUDE.md)

1. **입구 열거**: 이 스펙이 여는 입구는 **브로커 invoke(cap=memedit:user)** 하나. (HTTP update/delete는
   기존·별개로 이미 소유권 처리됨.) add(105)는 대상 없음, memedit는 **대상 있는 첫 브로커 부수효과**.
2. **입구별 소유권**: 대상 있는 쓰기 → (주체) principal 도출 user_id로 스코프 고정 + (대상×행) `user_owns`
   로 mem_id 소유 확인. **비-SQL 저장소(pgvector 전역 id)**라 SELECT-WHERE 불가 → 삭제/수정 *호출 직전*
   소유 확인(check-then-act; user_id가 principal-바인딩·기억은 소유자 안 바뀌므로 TOCTOU 창 저위험 —
   HTTP 라우트와 동일 잔존, 스펙에 명시 기록).
3. **단일 헬퍼**: `memory.user_owns` 하나를 HTTP·브로커가 공유(드리프트 0).
4. **존재 비노출**: 미소유·부재 mem_id는 **동일 error**("이 유저의 기억이 아닙니다")로 404-fold — 403/404
   구분 안 함(열거 오라클 제거, 068).
5. **검증 사다리 3런**: ① 단위(op 라우팅·승인=실행 일치·anti-leak args 무시), ② 실 mem0 통합
   (add→update 반영→delete 소멸 왕복·타 user mem_id 거부·머신 deny·**자가잠금 핀**=본인 기억 편집 가능),
   ③ codex 적대(여집합: args에 타 user mem_id로 남의 행 변조 시도·승인 우회·args user_id로 스코프
   리다이렉트·미소유 error 차이로 존재 캐기).
6. **자가-잠금 핀**: 본인 mem_id는 정상 수정/삭제됨(조임이 본인 접근을 막지 않음) — §5-② 별도 케이스.

## 검증

- `tests/verify_111_broker_memedit.py`: 위 3런. mock 아닌 실 mem0(통합 런은 seed+백엔드 필요). 통과.
- 무회귀: verify_104(읽기)·105(add) 재실행 — memedit 추가가 기존 능력 무영향. 통과.

## 적대 검증 (codex, rung 3) — 결과·정직화

codex challenge가 두 축을 짚음. 둘 다 **새 안전 위반이 아니라 정직한 경계**로 판정(주석 명시 +
안전 불변식 테스트 + OUT 기록으로 정직화):

- **[P1] check-then-act 비원자성**: `user_owns` 확인과 `update/delete`(scope 없는 전역 mem_id 호출)가
  원자적이지 않음. **하중 가정**: mem_id=전역 유일 UUID(mem0) + 기억 소유자 불변 → "확인 후 다른 유저
  행이 같은 mem_id로 해석"되는 창이 구조적으로 없음. **기존 HTTP 라우트와 동일 의미**(공유 user_owns) —
  111이 더 나빠진 게 아님. mem0 API에 scope 필터 mutation이 없어 원자 재구조화 불가 → **가정을 코드에
  명시**(broker invoke 주석) + 안전 불변식(교차유저 거부)은 verify_111이 실증 + scope-bound 원자
  mutation은 OUT(그런 백엔드는 fail-closed로 제공해야).
- **[P2 / 미문서 경계] 승인==실행 비강제**: 승인 payload는 표시용, 실행은 원 args(checkpoint replay).
  approval_for·invoke가 **같은 `_memedit_args`로 동일 정규화**하므로 승인==실행이 구성상 성립(105 memwrite와
  동일 패턴). codex도 미문서 경계로 판정 — normalized-args digest 비교는 향후 심화방어(105와 함께 OUT).

## 비목표 (OUT)

- 오케스트레이트 플로우 LLM 구동(그 플로우는 `{"text": query}`만 넘김 → mem_id 구조화 args 미지원).
  memedit는 **구조화 args를 만들 수 있는 호출자**(프로그램/향후 UI·A2A) 대상. 오케스트레이터-구동
  구조화 위임은 별개 후속.
- 승인 시 **현재 본문 표시**(approval_for는 동기 — async DB 조회 불가). 호출자/UI가 mem_id→본문을
  미리 해석해 보여주는 건 그쪽 관심사. 브로커 승인은 *액션*(op·mem_id·새 본문) 가시성만.
- 공유 카탈로그 per-cap 인가·자원 소유권 → **스펙 112**(별개 단위).
