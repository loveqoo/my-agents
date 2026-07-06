# 산출물형 에이전트 저작 가이드 (개발자용)

> 대상: `produce()` 로직을 코드로 작성하는 개발자.
> 일반사용자(어드민에서 에이전트를 만들고 쓰는 사람)용은 [artifact-agent-user.md](./artifact-agent-user.md).
> 설계 배경·검증은 스펙 [`docs/spec/188-artifact-agent.md`](../spec/188-artifact-agent.md).

## 1. 산출물형 에이전트란

대화를 통해 **구조화된 데이터(산출물)를 모아서 완성하는** 에이전트다. 일반 채팅 에이전트가 "말로
답한다"면, 산출물형은 "**결과물(JSON)을 만든다**" — 출장 신청서, 타겟팅 조건, 설문 응답처럼.

핵심 뼈대는 딱 세 단계다:

```
produce(로직) → Artifact(산출물) → sink(처리: API 호출·UI 콜백 등)
```

당신이 채우는 건 가운데 **`produce()` 하나뿐**이다. 멀티턴 대화, 폼, 재개, 검증 같은 배관은 전부
조상 클래스(`ArtifactAgentBase`)가 갖고 있다.

## 2. 가장 짧은 예제 — 고정 필드 채우기

`ArtifactAgentBase`를 물려받아 `NAME`/`DESCRIPTION`을 정하고 `produce()`만 구현한다:

```python
from agent.flows.artifact import ArtifactAgentBase, ProduceContext, Artifact

class TravelRequestAgent(ArtifactAgentBase):
    NAME = "travel_request"
    DESCRIPTION = "출장 신청서를 대화로 채우는 에이전트"

    async def produce(self, ctx: ProduceContext) -> Artifact:
        destination = ctx.ask("목적지를 알려주세요 (예: 서울, 부산)")
        period      = ctx.ask("기간을 알려주세요 (예: 3월 2일부터 3일간)")
        budget      = ctx.ask("예산을 알려주세요 (예: 50만원)")
        return Artifact(
            kind="travel-request",
            data={"destination": destination, "period": period, "budget": budget},
        )
```

`ctx.ask()`가 질문을 던지면 대화가 거기서 멈추고 사용자의 다음 입력을 기다린다. 답이 오면 그 자리에서
이어진다. **여러 번 `ask`해도** 뼈대가 알아서 멀티턴으로 이어 붙인다 — `produce()` 안에서는 그냥
동기 코드처럼 읽으면 된다.

> 실제 등록된 데모 `SlotFillDemoAgent`(`flows/artifact.py`)는 여기에 "빈 답이면 3회까지 되묻기"만
> 더한 형태다.

## 3. 프리미티브 — 이 5개만 쓴다 (닫힌 집합)

`produce()` 안에서 바깥 세계에 닿는 통로는 `ctx`의 이 다섯뿐이다. **이게 보안·결정성 경계다** —
파일·네트워크를 직접 만지지 말고 반드시 이 프리미티브를 거친다.

| 프리미티브 | 시그니처 | 언제 쓰나 |
|---|---|---|
| `ctx.ask` | `ask(question: str) -> str` | 자유 텍스트 한 줄을 받을 때. 대화가 멈추고 다음 입력을 반환. |
| `ctx.form` | `await form(fields, prefill=None, *, confirm=False) -> dict` | 후보(SelectBox)·여러 칸을 **폼**으로 한 번에 받을 때. |
| `ctx.rag` | `await rag(collection, query) -> 결과` | 등록된 RAG 컬렉션을 검색할 때(브로커 경유 — 권한 그대로). |
| `ctx.tool` | `await tool(cap_id, args: dict) -> 결과` | 등록된 MCP 도구를 부를 때(브로커 경유 — 배선 권한 그대로). |
| `ctx.extract` | `await extract(instruction, text) -> dict` | 자유 텍스트에서 LLM으로 값을 뽑을 때(모델 없으면 `{}`). |
| `ctx.text` | (속성) | 이번 실행을 시작한 사용자의 첫 발화. |

`rag`/`tool`은 **브로커를 거치므로 새 권한이 생기지 않는다** — 에이전트에 연결된 컬렉션/도구만 닿고,
호출자 RBAC로 교집합된다. 안 붙은 자원은 조용히 빈 결과(deny-by-default).

## 4. 폼 쓰기 — 필드 명세와 이중 입력

`ctx.form(fields, prefill, confirm=)`의 `fields`는 dict 리스트다. 각 필드 형태:

```python
{
    "key": "purchase_history",     # 결과 dict의 키(필수)
    "label": "구매이력",            # 화면 표시 이름
    "candidates": ["최근", "7일 전", "최근 한 달"],  # 있으면 SelectBox, 없으면 자유 입력
    "required": True,              # 기본 True
}
```

폼을 띄우면 사용자는 **두 가지 방법**으로 답할 수 있고, 뼈대가 둘 다 같은 슬롯에 병합한다(이중 입력):

1. **폼 제출** — 후보 중에서 골라 제출. 뼈대가 `validate_form_values`로 후보 밖 값·빈 값을 걸러낸다.
2. **채팅 텍스트** — 폼이 떠 있어도 그냥 말로 입력. 후보 문자열이 텍스트에 있으면 결정적으로 채우고,
   남은 자유 칸은 `extract`(LLM)로 보완한다.

`prefill`로 미리 채워둘 수 있다(예: 첫 발화에서 이미 파악한 값). `confirm=True`면 프리필이 완전해도
**최소 1회는 폼을 보여주고 사용자 확인을 받는다**.

> **함정 주의(적대 검토로 배움):** 텍스트 병합은 "서울 말고 부산" 같은 부정어를 잘못 채울 수 있다.
> 그래서 `confirm=True`면 텍스트로 값이 바뀐 뒤 **곧장 확정하지 않고 갱신된 폼을 다시 보여준다** —
> 최종 확정은 사용자가 **폼 제출**을 눌러야만 일어난다. 확정이 중요한 산출물이면 `confirm=True`를 켜라.

## 5. 동적 예제 — 발화에서 폼을 만들어내기

필드를 코드에 고정하지 않고 **런타임에 합성**할 수도 있다. 등록된 `TargetingDemoAgent`가 그 예다
(사용자 시나리오: "최근 구매 이력 있는 30대 서울 남성" → 요소 분해 → 폼 자동 생성):

```python
async def produce(self, ctx: ProduceContext) -> Artifact:
    utter = ctx.text or ctx.ask("어떤 유저를 타겟팅할까요? 조건을 문장으로 말씀해 주세요.")

    # ① 카탈로그 목록(도구). 없으면 빈 폼을 조용히 띄우지 말고 정직하게 종료.
    listing = await ctx.tool(f"mcp:{self.CATALOG_MCP}/list_entities", {})
    catalog = _first_json_obj(getattr(listing, "text", "") or "").get("entities") or []
    if not catalog:
        return Artifact(kind="targeting", data={"conditions": [], "error": "카탈로그 없음"})

    # ② 발화에서 요소 매칭 = RAG 마커 ∪ 카탈로그 동의어(결정적 폴백)
    rag_res = await ctx.rag(self.RAG_COLLECTION, utter)
    matched = match_entities(utter, catalog)  # + rag 결과 합집합(생략)

    # ③ 엔티티별 후보를 조회(도구) → 폼 필드로 합성
    fields = []
    for e in matched:
        detail = _first_json_obj((await ctx.tool(f"mcp:{self.CATALOG_MCP}/get_entity",
                                                 {"entity_id": e["id"]})).text)
        fields.append({"key": e["id"], "label": detail["label"],
                       "candidates": detail["candidates"], "required": True})

    # ④ 발화로 미리 채우고 → 폼 제시(확인) → 결과 조립
    prefill = merge_text_into_fields(fields, {}, utter)
    values = await ctx.form(fields, prefill, confirm=True)
    return Artifact(kind="targeting",
                    data={"conditions": [{"entity_id": f["key"], "value": values.get(f["key"])}
                                         for f in fields]})
```

핵심은 **뼈대 파일을 한 줄도 안 고치고** 이 둘째 구현이 붙는다는 점이다 — 추상이 새지 않았다는 증거.

## 6. 등록하기

작성한 클래스를 `runtime.py`의 부트스트랩에서 한 줄로 등록한다:

```python
# packages/agent/src/agent/runtime.py  — _bootstrap_builtins() 안
from .flows.artifact import TravelRequestAgent
register_agent("travel_request", TravelRequestAgent)   # 이름 = 어드민에서 고를 impl 키
```

이제 어드민에서 에이전트를 만들 때 `impl: "travel_request"`로 이 구현을 선택할 수 있다(그 흐름은
[일반사용자 가이드](./artifact-agent-user.md) 참고).

## 7. 반드시 지킬 규칙 (안 지키면 조용히 깨진다)

산출물형 에이전트는 LangGraph의 **interrupt 재실행** 위에서 돈다 — 대화가 재개될 때마다 `produce()`가
**처음부터 다시 실행**되고, 이미 지난 프리미티브 호출은 기록된 값으로 리플레이된다. 여기서 세 규칙:

1. **결정성 계약** — 프리미티브 반환값 *외의* 비결정 입력(현재 시각·난수·전역 상태)으로 분기하지 마라.
   재실행 때 분기가 달라지면 리플레이가 어긋난다(replay drift).
2. **프리미티브는 멱등이어야** — `ctx.tool`/`ctx.rag`가 부르는 도구는 부수효과가 없어야 한다. 스텝 캐시는
   인메모리라 프로세스 재시작·과다 동시 세션 시 재호출될 수 있다. (서빙 MCP는 이 불변식을
   `_SIDE_EFFECT_FREE_TOOLS`로 강제한다 — 부수효과 있는 도구를 산출물 수집에 쓰지 마라.)
3. **닫힌 집합은 규율이지 샌드박스가 아니다** — `produce()`는 코드로 리뷰되어 등록되는 **신뢰 1급 구현**이다.
   `ctx._model`/`ctx._broker`에 직접 손대거나 `import os`로 파일을 만지는 건 문법상 가능하지만 규율 위반이다.
   미신뢰 제3자 코드를 `produce()`로 받는 설계는 별도 프로세스 격리가 필요하다(현 범위 밖).

## 8. 검증

새 에이전트를 만들면 `tests/verify_188_artifact.py`의 패턴을 따라 검증한다:

- **단위/그래프**: `build_graph()`로 그래프를 만들고 `ainvoke` + `Command(resume=...)`로 멀티턴을 직접
  구동해 최종 `artifact`를 확인한다(순수함수는 `validate_form_values`·`merge_text_into_fields` 등 직접 호출).
- **e2e**: `tests/browser/verify-artifact-*.mjs`처럼 플레이그라운드에서 실제 왕복을 돌린다.
- 산출물이 사용자별 데이터·권한을 만지면 **적대 검증(codex)**까지 — 후보 밖 값 제출·타 세션 재개·미배선
  도구 사용을 실제로 시도해 막히는지 확인한다(스펙 188 적대 검토 절 참고).
