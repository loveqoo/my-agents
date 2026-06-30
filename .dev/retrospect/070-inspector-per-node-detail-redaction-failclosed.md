# 070 — 턴 인스펙터 노드별 세부정보: 키기반 redaction의 한계와 fail-closed 노출

스펙: `docs/spec/086-inspector-per-node-detail.md`
관련 learning: 089(이번), [[cap-the-raw-source-not-the-buffer]]=059, [[adversarial-review-before-destructive-ship]], [[installed-guard-isnt-covering-guard]]

## 무엇을 했나

인스펙터 "LangGraph 경로"가 노드 *이름*만 보여주던 걸, `updates` 스트림 청크의 *값*(노드 상태 델타)을
살려 ① 노드별 실측 ms(update 도착 간격) + ② 상태 델타 안전 요약을 싣게 했다. 085가 청산한 노드열
위에 "무슨 일이 있었나"를 더한다. 사용자에게 노출되는 표면이라 **비밀 누출 0**이 핵심 불변식.

## 무엇이 어긋났고 무엇을 배웠나

### 1. 키기반 redaction은 *값 자체* 비밀을 못 막는다 (codex F2 → learning 089)

첫 설계는 `_SENSITIVE_KEY` 정규식으로 *키 이름*(`api_key`·`token`…)을 보고 마스킹했다. 자가 단위
테스트는 `api_key`·중첩 dict·변종까지 다 초록이었다 — **내가 상상한 실패(민감한 *이름*의 키)만
확인**했다. codex가 여집합을 짚었다: `{"note": "<secret>"}`·`{"비밀번호": "..."}`처럼 *평범하거나
비영문인 키에 비밀 값*이 들어오면 키-패턴이 못 잡아 값이 그대로 화면에 뜬다. 키기반은 필요조건이지
충분조건이 아니다.

처방: **값 원문 노출을 최소 allowlist로 뒤집었다(fail-closed).** 값을 원문으로 보여주는 키는 "이
기능의 존재이유가 그 값을 보여주는 것"인 필드 — 현재 `plan` 하나뿐. 그 외 임의 키의 문자열 값은
`key: <N자>`로 *크기만*. 처음엔 allowlist를 `{plan, step, next, status, stage}`로 넓게 잡았다가,
"임의 에이전트가 `status`에 비밀을 담을 수 있다"를 떠올려 `{plan}`으로 좁혔다 — 보안경계에서
allowlist는 *작을수록* 옳다(편의 키를 넣는 순간 그 키는 "절대 비밀 아님"을 보증해야 한다).

### 2. 캡은 raw에서 budgeted로, 그리고 *이중 캡*은 정직성을 깬다 (codex F3 + 후속)

캡을 join *후* 최종 문자열에만 걸어, 거대 값을 통째 만든 뒤 자르고 있었다 — learning 059
([[cap-the-raw-source-not-the-buffer]]) "막은 척"의 정확한 재발. 각 값을 append *전에* budgeted
캡으로 바꿨다(`val[:limit]`만 복사). 그런데 고치고 나니 단위 테스트가 *새* 거짓을 드러냈다: 필드 캡과
노드 전체 캡이 같은 300이라, 단일 거대 `plan`이 필드 캡으로 잘린 뒤(310자) 바깥 join 캡에 *재차*
잘려 "…(10자 생략)"이라는 **거짓 생략 길이**를 냈다(실제론 700자 생략). 필드 캡(300)/노드 캡(1200)을
분리해 단일 필드가 이중 캡되지 않게 했다. **테스트가 내 수정의 부작용을 잡았다** — 검증 사다리가
일했다.

### 3. 같은 비밀이 *형제 trace 표면*으로 샌다 (codex F1 → 087 분리)

086은 노드 summary 표면을 단단히 했지만, codex는 *다른* 표면을 짚었다: MCP/tool 호출 인자
(`calls_sink.args = kwargs`)·result가 원문 그대로 trace에 실리고 Inspector가 `JSON.stringify`로
렌더한다. 086 redaction과 무관하게 같은 인스펙터 화면에서 비밀이 샌다. **한 표면을 가려도 형제
표면은 안 가려진다** — "입구를 닫힌집합으로 세라"(learning 070·088)의 redaction판. P0지만 086이
도입한 게 아니고(085 이전 pre-existing) 별 표면이라, 086 per-spec 커밋을 오염시키지 않게 **087로
분리**했다. 086이 만든 fail-closed 요약 도구를 087이 재사용한다.

### 4. fail-closed는 예외 경로까지 (codex F5)

비문자 키가 `_SENSITIVE_KEY.search(key)`에서 TypeError를 던지면 요약이 죽고 chat loop가 error
프레임으로 종료된다 — 표시 보조 기능이 본 스트림을 깬다. `str(key)` 정규화 + 요약기 전체
try/except로 "요약 실패 = None(행 미표시)" fail-closed. 보안 fail-closed와 가용성 fail-closed는
같은 자세다: *불확실하면 적게 노출하고 죽지 마라*.

## 핵심 한 줄

사람에게 보여줄 표면에서 비밀 누출 0을 원하면, 키 *blocklist*가 아니라 값 *allowlist*로(deny-by-default
노출), 캡은 raw에서 budgeted로, 그리고 *모든 형제 표면*에 같은 정책을 — 한 표면만 가리면 옆에서 샌다.
자가 테스트는 상상한 실패(민감한 이름)만 보고, 적대자가 여집합(평범한 이름의 비밀 값)을 짚는다.
