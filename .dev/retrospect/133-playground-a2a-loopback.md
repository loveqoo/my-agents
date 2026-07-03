# 133 — 플레이그라운드 A2A 루프백 테스트 (스펙 155, 실사용 #8)

자율 루프 6건차(B 시리즈). 내부 노출 에이전트를 플레이그라운드에서 **직접(/chat)** 과
**A2A 경유(/agents/{id}/a2a)** 두 방식으로 테스트할 수 있게 했다.

## 무엇을 했나
- 클라 A2A 전송 `streamChatA2A` + `handleA2AFrame`(api.ts) — A2A message/stream SSE(status-update
  프레임 → parts[].text 델타, final/[DONE] 종결, error 표면화). direct용 `handleFrame`과 프레임
  형태가 달라 별도 파서.
- 플레이그라운드 헤더에 Segmented "직접/A2A" 토글(노출 에이전트 한정), send() 분기(A2A면 단발 text만).
- 154 후속 낡은 게이트 정직화 — A2A 배지 게이트 `source==='ui'` → `source∈{ui,code}`(154가 code
  중계 공개를 허용했는데 배지/토글이 code를 놓치고 있었다).

## 배운 것 (상기용)
1. **프로토콜 경로는 프레임 계약이 다르면 파서도 다르다.** direct SSE(`data:{text}`)와 A2A
   SSE(`data:{jsonrpc,result:status-update}`)를 한 파서로 뭉치면 조용히 토큰을 흘린다. 파서를 나누되,
   **스트림 엔드포인트가 스트림 아닌 평문 에러 바디를 줄 수 있다**는 걸 잊지 마라 — message/stream
   경로도 dispatch 전 에러(루프가드 -32000·미지원 메서드)는 평문 JSON-RPC로 반환한다. `data:` 없는
   프레임을 통째 JSON으로 접는 폴백이 없었으면 루프가드 에러가 화면에 안 떴다(verify V3가 잡음).
2. **새 실행 경로는 "옛 경로가 주던 것"의 여집합을 상속하지 않는다.** A2A 서빙은 세션/히스토리/trace/
   오버라이드를 안 넘긴다(단발). 그런데 UI(세션 피커·인스펙터)는 direct 기준으로 짜여 있어, A2A 턴을
   기존 세션에 섞으면 "이어 쓴 것"처럼 보이지만 비영속이다(codex Med). **경계가 정직하려면 UI가 그
   경계를 *가시적으로* 말해야 한다** — 툴팁(hover-only)로는 부족, 인라인 힌트로. [[complement-attack-can-be-honest-boundary]]
   의 재현: 여집합 공격이 성공해도 코드결함이 아니라 미문서 경계 → 주석+가시 표기+정직 기록으로 마감.
3. **한 스펙의 완화가 딴 화면의 낡은 불변식을 남긴다.** 154가 "exposed ⟹ source=ui"를 깨고 code를
   허용했는데, 플레이그라운드 배지는 옛 불변식을 그대로 코드에 박아뒀다. 완화 스펙은 그 불변식을 *읽는
   모든 지점*을 훑어야 한다(grep으로 `source === 'ui'` 전수). [[installed-guard-isnt-covering-guard]]의
   UI판 — "완화했다"≠"완화가 모든 소비 지점에 반영됨".

## codex 적대 리뷰 (High 0)
- Med(미문서 경계): A2A 단발이 기존 세션 UI에 섞임 → 가시 힌트로 정직화(Fix A).
- Low(미문서 경계): A2A 전송 후 인스펙터가 직전 direct trace를 stale 표시 → selectedTurn을 새
  A2A 턴으로 이동해 빈 상태 표시(Fix B).
- 인증 누락·external 우회·조기 return의 finally 스킵·AbortError 오렌더는 없음(확인됨).

## 검증
- verify_155 6/6(ui/code message/stream·루프가드 -32000·404 게이트·final+[DONE] 종결).
- e2e: 노출 에이전트 A2A 토글·A2A 경유 응답 렌더·미노출 에이전트 토글 부재.
- codex 여집합 리뷰 High 0, 경계 2건 정직화 반영.
