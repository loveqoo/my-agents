# 092 — 브로커 메모리 수정/삭제 능력 (스펙 111)

## 무엇을 / 왜

브로커 메모리 능력을 읽기(104)·저장(105)에서 **수정/삭제**로 확장. add와 결정적 차이: update/delete는
**기존 mem_id 대상**이라 소유권 검증이 선행돼야 함(learning 054·069). 소유권 경계 스펙 →
`docs/spec/CLAUDE.md` RBAC 체크리스트 자동 적용. 사용자 요청 "메모리 수정/삭제 + 인가강화"의 앞 절반
(뒤 절반=공유 카탈로그 인가는 스펙 112로 분리).

## 한 일

- **kind `memedit`, cap `memedit:user`**(MemoryWriteProvider 105 미러). args `{op, mem_id, text?}`.
- **소유권 술어 단일화**: `memory.user_owns(user_id, mem_id, mem_cfg)` 추출 → HTTP `_assert_user_owns`와
  브로커 invoke가 공유(드리프트 0).
- **방어 3겹**: principal 도출 user_id 고정(anti-leak) + `user_owns` 소유권 선행(미소유·부재 동일 error
  404-fold) + 승인 게이트 항상(삭제 비가역 → member 시드 없음 fail-closed).
- **검증 3런**: 단위(op 라우팅·승인=실행·anti-leak 양방향) + 그래프 게이트(approve 1회/reject 무변경) +
  **실 mem0 통합**(add→update 반영→delete 소멸·교차유저 거부·자가잠금 핀). verify_104/105 무회귀.

## 잘된 것

- **RBAC 체크리스트를 스펙에 먼저 답하고 코드가 따라감** — 입구 열거·404-fold·단일 헬퍼·자가잠금 핀이
  설계 단계에서 박혀, verify가 그걸 그대로 실증. 앞선 learning(054/068/069/070)이 Context에서 상기돼
  복리로 작동(인덱스 후크로 싸게).
- **적대 검증(codex)이 하중 가정을 드러냄**: check-then-act 비원자성 [P1]을 짚음 → mem_id=전역 UUID +
  소유자 불변이라는 **암묵 가정**을 코드에 명시하게 만듦(learning 111). 자가검증이었으면 "교차유저 거부
  초록"에 만족하고 이 가정을 안 적었을 것.
- **정직화로 처리**(memory: 여집합 공격이 성공해도 안전위반 아니면 미문서 경계): P1은 기존 HTTP 라우트와
  동일 잔존이라 "고침" 아닌 "가정 명시+안전불변식+OUT", P2는 codex도 미문서 경계로 판정(105와 동일).

## 배운 것 / 함정

- **"각 고리 초록" ≠ "가정 검증"**(learning 111): 소유권 확인은 초록이었지만 *그게 안전한 이유*(mem_id
  유일성)는 미기록이었다. 적대 타자가 그 하중 가정을 표면화 — 검증 사다리 rung3의 값.
- codex exec 최종 메시지가 stdout에 안 실리는 라우팅 이슈 — `--json`도 불안정, **포그라운드 + `2>&1`
  병합 + 넉넉한 타임아웃(540s)**으로야 verbatim findings를 얻음.

## 검증 안 함(사유)

- 오케스트레이트 LLM 구동(text-only flow는 mem_id 구조화 args 미지원) — 프로그램/A2A 호출자 대상, OUT.
- scope-bound 원자 mutation — mem0 API에 scope 필터 없음, 재구조화 불가(백엔드 계약 변경은 별개).
