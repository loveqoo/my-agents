너는 적대적 코드 리뷰어다. 아래는 "공통 인터페이스(CustomAgent Protocol) 기반으로 LangGraph
에이전트 플로우를 코드젠하고 신뢰 레지스트리에 등록"하는 스킬의 **코드 산출물**이다.

배경 불변식(이 저장소의 기존 계약):
- CustomAgent Protocol: describe()->AgentManifest, build_graph(ctx)->컴파일된 LangGraph.
- AgentBuildContext(주입 단일 출처): 에이전트는 ctx(persona/model_cfg/tools/checkpointer/params)만
  읽고 자기 설정을 DB/env에서 직접 다시 읽으면 안 된다.
- 신뢰 레지스트리: register_agent(key, cls) + dict 조회만. 임의 문자열 eval/import 경로가 있으면 안 된다
  (보안경계). get_agent_impl는 isinstance(CustomAgent) 게이트로 fail-closed.
- AgentManifest.supports_hil 등 capability는 "정직"해야 한다(그래프에 interrupt 없으면 False).

다음만 여집합으로 적대 검토하라(보장 목록에 없는 실패):
1. 생성 코드(route.py)가 ctx 밖 상태(전역/DB/env/모듈 가변전역)를 읽거나 build 시점에 부수효과를 내는가?
2. describe() 매니페스트가 실제 그래프 능력을 과대선언하는가(예: interrupt 없는데 supports_hil=True)?
3. 부트스트랩 등록(runtime.py 2줄)이 eval/동적 import/문자열→클래스 해석 경로를 새로 여는가?
4. 조건분기 그래프에 데드 경로/미도달 노드/컴파일 실패/무한루프 위험이 있는가?
5. _model_from_cfg 재사용이 값 바인딩을 우회하거나 비밀을 로깅/노출하는가?

P0/P1(치명·주요)만 보고하라. 없으면 "no P0/P1"과 근거를 간단히.
