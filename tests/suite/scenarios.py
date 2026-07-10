"""시나리오 매트릭스 (스펙 288) — 데이터 선언.

각 시나리오: {key, agent(픽스처 별칭), turns([str]), overrides(dict|None), expect([단언 스펙])}.
단언은 마지막 턴의 파싱 결과(_sse.parse_sse)와 trace에 적용 — 어휘는 run.py의 ASSERTS가 소유.
프롬프트는 실모델 대상이라 명령형으로 강하게(도구 사용은 "반드시 … 도구를 호출"), 단언은
기록(trace)으로만 하고 텍스트는 고유 토큰 포함 여부까지만 본다(문장 일치 금지 — 스펙 288 원칙).

승인 왕복·비영속 DB 불변·부트스트랩 멱등·프리플라이트 단위는 run.py의 커스텀 시나리오가 소유.
"""

from __future__ import annotations

from .fixtures import FACT_TOKEN, KB_NAME, PREF_TOKEN, TOOL_ECHO

SECRET = "9427"

SCENARIOS: list[dict] = [
    # ── 직접형: 도구/RAG/기억 축 ──
    dict(key="direct-tool-echo", agent="direct",
         turns=["반드시 echo 도구를 호출해서 'ping-288' 텍스트를 그대로 돌려받고, 결과를 알려줘."],
         expect=[("tool_called", "echo", 1), ("text_nonempty",)]),
    dict(key="direct-no-tool", agent="direct",
         turns=["도구를 사용하지 말고 답해: 1 더하기 1은? 숫자만."],
         expect=[("tools_called_zero",), ("text_nonempty",)]),
    dict(key="direct-rag-hit", agent="direct",
         turns=[f"반드시 문서 검색 도구로 {KB_NAME} 문서에서 '회사 표준 배포 코드네임'을 검색해서, 찾은 코드네임을 그대로 알려줘."],
         expect=[("rag_called",), ("text_contains", FACT_TOKEN)]),
    dict(key="direct-memory-recall", agent="direct",
         turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
         expect=[("memory_hit", PREF_TOKEN), ("text_nonempty",)]),

    # ── 단기 기억(세션) 축 — 기억 간섭이 없는 bare 에이전트로 격리 ──
    dict(key="bare-session-recall", agent="bare",
         turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", "방금 내가 알려준 비밀 코드를 숫자만으로 답해."],
         expect=[("text_contains", SECRET)]),
    dict(key="bare-historydepth0-override", agent="bare",
         overrides={"historyDepth": 0},
         turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", "방금 내가 알려준 비밀 코드를 숫자만으로 답해."],
         expect=[("text_not_contains", SECRET), ("override_key", "historyDepth")]),

    # ── 오버라이드 축 (base=suite-direct) + 저장 설정 대조군 ──
    dict(key="direct-override-notools", agent="direct",
         overrides={"tools": [], "mcps": []},
         turns=["반드시 echo 도구를 호출해서 'x'를 돌려받아 알려줘."],
         expect=[("tool_not_called", "echo"), ("override_key", "tools")]),
    dict(key="direct-override-nomem", agent="direct",
         overrides={"memories": []},
         turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
         expect=[("memory_absent",), ("override_key", "memories")]),
    dict(key="direct-override-norag", agent="direct",
         overrides={"vectorTables": []},
         turns=["문서 검색 도구로 회사 표준 배포 코드네임을 검색해서 알려줘."],
         expect=[("rag_not_called",), ("override_key", "vectorTables")]),
    dict(key="direct-override-temperature", agent="direct",
         overrides={"temperature": 0.2},
         turns=["'안녕하세요'라고만 답해줘."],
         expect=[("override_key", "temperature"), ("text_nonempty",)]),
    dict(key="direct-control-combined", agent="direct",
         turns=["반드시 echo 도구로 'combo-288'을 돌려받고, 내 커피 취향 기억도 확인해서 한 줄로 답해줘."],
         expect=[("tool_called", "echo", 1), ("memory_hit", PREF_TOKEN), ("override_absent",)]),

    # ── 비영속(채팅 자체 — DB 불변·승인 거부는 run.py 커스텀) ──
    dict(key="ephemeral-chat", agent="ephemeral",
         turns=["1 더하기 1은? 숫자만 답해."],
         expect=[("text_nonempty",)]),

    # ── 노드형(스킬: pipeline) — 노드 도구/RAG/기억 + 오버라이드는 run.py 커스텀 ──
    dict(key="pipeline-rag-and-tool", agent="pipeline",
         turns=["회사 표준 배포 코드네임이 뭐야?"],
         expect=[("rag_called",), ("tool_called", "echo", 1), ("text_nonempty",)]),
    dict(key="pipeline-override-temperature", agent="pipeline",
         overrides={"temperature": 0.3},
         turns=["안녕이라고 답해줘."],
         expect=[("override_key", "temperature"), ("text_nonempty",)]),
    # 노드형 회상은 노드별 프록시(268 P2) — trace.memoryRecalls(건수)로 단언(memories 표면과 다름).
    dict(key="pipeline-memory-recall", agent="pipeline",
         turns=["내 커피 취향을 반영해서 음료 하나만 추천해줘."],
         expect=[("memory_recall_min", 1), ("text_nonempty",)]),

    # ── 조율형(스킬: orchestrate) — 위임 기록 + 오버라이드 대조 ──
    # 발견(discover)은 lexical 랭킹(rank_candidates — 겹침 0 후보 제외)이라 프롬프트에 위임 대상
    # 이름("suite-direct")이 있어야 후보가 뜬다(실측 — 일반어 프롬프트는 위임 0).
    dict(key="orch-delegate", agent="orchestrate",
         turns=["suite-direct 에이전트에게 위임해서 답을 받아줘: 1 더하기 1은?"],
         expect=[("broker_min", 1), ("text_nonempty",)]),
    dict(key="orch-override-nocaps", agent="orchestrate",
         overrides={"capabilities": []},
         turns=["suite-direct 에이전트에게 위임해서 답을 받아줘: 1 더하기 1은?"],
         expect=[("broker_zero",), ("override_key", "capabilities")]),
    dict(key="orch-memory-recall", agent="orchestrate",
         turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
         expect=[("memory_hit", PREF_TOKEN)]),

    # ── 분기형(스킬: route) — 결정적 분기("?" 유무)를 trace 타임라인으로 ──
    dict(key="route-branch-a", agent="route",
         turns=["대한민국의 수도는 어디야?"],
         expect=[("graph_node", "answer_a"), ("graph_node_absent", "answer_b")]),
    dict(key="route-branch-b", agent="route",
         turns=["오늘 배운 내용을 두 문장으로 정리해 줘."],
         expect=[("graph_node", "answer_b"), ("graph_node_absent", "answer_a")]),
    dict(key="route-memory-recall", agent="route",
         turns=["내 커피 취향이 뭐였지?"],
         expect=[("memory_hit", PREF_TOKEN), ("graph_node", "answer_a")]),

    # ── 계획-실행형(스킬: plan_execute) ──
    dict(key="plan-tool", agent="plan",
         turns=["반드시 echo 도구를 호출해 'plan-288'을 돌려받아 결과를 알려줘."],
         expect=[("tool_called", "echo", 1)]),
    dict(key="plan-rag", agent="plan",
         turns=[f"반드시 문서 검색 도구로 {KB_NAME}에서 회사 표준 배포 코드네임을 검색해 알려줘."],
         expect=[("rag_called",)]),
]

# 노드 오버라이드(287) 커스텀 시나리오가 쓰는 상수 — run.py가 소유·참조.
NODE_OVERRIDE_TOKEN = "NODE-OV-288"
NODE_OVERRIDE_ECHO_PROMPT = (
    f"반드시 echo 도구를 한 번 호출해 '{NODE_OVERRIDE_TOKEN}' 텍스트를 그대로 넣고, 결과를 전달하세요."
)
ECHO_TOOL = TOOL_ECHO
