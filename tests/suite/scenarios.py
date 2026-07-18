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
# 실모델 변덕 대응(실측): "비밀 코드" 회수 질문에 가짜 함수호출 구문을 내는 경우가 있어
# 도구·함수 금지를 명시한다(기록 단언과 무관 — 텍스트 회수 안정화용).
RECALL_PROMPT = "방금 내가 알려준 비밀 코드를 숫자만으로 답해. 도구나 함수 호출은 하지 마."

SCENARIOS: list[dict] = [
    # ── 직접형: 도구/RAG/기억 축 ──
    dict(
        key="direct-tool-echo",
        agent="direct",
        turns=["반드시 echo 도구를 호출해서 'ping-288' 텍스트를 그대로 돌려받고, 결과를 알려줘."],
        expect=[("tool_called", "echo", 1), ("text_nonempty",)],
    ),
    dict(
        key="direct-no-tool",
        agent="direct",
        turns=["도구를 사용하지 말고 답해: 1 더하기 1은? 숫자만."],
        expect=[("tools_called_zero",), ("text_nonempty",)],
    ),
    dict(
        key="direct-rag-hit",
        agent="direct",
        turns=[
            f"반드시 문서 검색 도구로 {KB_NAME} 문서에서 '회사 표준 배포 코드네임'을 검색해서, 찾은 코드네임을 그대로 알려줘."
        ],
        expect=[("rag_called",), ("text_contains", FACT_TOKEN)],
    ),
    dict(
        key="direct-memory-recall",
        agent="direct",
        turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
        expect=[("memory_hit", PREF_TOKEN), ("text_nonempty",)],
    ),
    # ── 단기 기억(세션) 축 — 기억 간섭이 없는 bare 에이전트로 격리 ──
    dict(
        key="bare-session-recall",
        agent="bare",
        turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", RECALL_PROMPT],
        expect=[("text_contains", SECRET), ("history_restore_absent",)],
    ),  # 클라 모드=서버 재구성 없음(289 무회귀 축)
    # 히스토리 서버 재구성(스펙 289 P1) — 외부 연동 계약: sessionId+새 메시지만으로 이전 대화 승계.
    dict(
        key="bare-server-history",
        agent="bare",
        history="server",
        turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", RECALL_PROMPT],
        expect=[("text_contains", SECRET), ("history_restored_min", 2)],
    ),
    # 노드형도 자동 승계(사용자 확인 질문) — 노드 대화 창(historyWindows)이 재구성분을 실제로 봤는지.
    dict(
        key="pipeline-server-history",
        agent="pipeline",
        history="server",
        turns=[
            f"내 비밀 코드는 {SECRET}이야. 기억해 둬.",
            "방금 내가 알려준 비밀 코드를 알려줘. 문서 검색이나 도구 호출은 하지 마.",
        ],
        expect=[("history_restored_min", 2), ("history_window_min", 2)],
    ),
    dict(
        key="bare-historydepth0-override",
        agent="bare",
        overrides={"historyDepth": 0},
        turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", RECALL_PROMPT],
        expect=[("text_not_contains", SECRET), ("override_key", "historyDepth")],
    ),
    # ── 오버라이드 축 (base=suite-direct) + 저장 설정 대조군 ──
    dict(
        key="direct-override-notools",
        agent="direct",
        overrides={"tools": [], "mcps": []},
        turns=["반드시 echo 도구를 호출해서 'x'를 돌려받아 알려줘."],
        expect=[("tool_not_called", "echo"), ("override_key", "tools")],
    ),
    dict(
        key="direct-override-nomem",
        agent="direct",
        overrides={"memories": []},
        turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
        expect=[("memory_absent",), ("override_key", "memories")],
    ),
    dict(
        key="direct-override-norag",
        agent="direct",
        overrides={"vectorTables": []},
        turns=["문서 검색 도구로 회사 표준 배포 코드네임을 검색해서 알려줘."],
        expect=[("rag_not_called",), ("override_key", "vectorTables")],
    ),
    dict(
        key="direct-override-temperature",
        agent="direct",
        overrides={"temperature": 0.2},
        turns=["'안녕하세요'라고만 답해줘."],
        expect=[("override_key", "temperature"), ("text_nonempty",)],
    ),
    dict(
        key="direct-control-combined",
        agent="direct",
        turns=[
            "반드시 echo 도구로 'combo-288'을 돌려받고, 내 커피 취향 기억도 확인해서 한 줄로 답해줘."
        ],
        expect=[("tool_called", "echo", 1), ("memory_hit", PREF_TOKEN), ("override_absent",)],
    ),
    # ── 비영속(채팅 자체 — DB 불변·승인 거부는 run.py 커스텀) ──
    dict(
        key="ephemeral-chat",
        agent="ephemeral",
        turns=["1 더하기 1은? 숫자만 답해."],
        expect=[("text_nonempty",)],
    ),
    # ── 노드형(스킬: pipeline) — 노드 도구/RAG/기억 + 오버라이드는 run.py 커스텀 ──
    # 발화를 도구 기대와 정렬(게이트 정비 2026-07-14) — 구 발화("코드네임이 뭐야?")는 echo 요구가
    # 노드 시스템 프롬프트에만 있어 qwen3.6이 상습 무시(강화 문구로도 0/6 실측). 사용자 발화가
    # 직접 요구하면 결정적으로 호출(실측 — 모델은 유저 지시>노드 지시). 단언은 불변(커버리지 보존).
    dict(
        key="pipeline-rag-and-tool",
        agent="pipeline",
        turns=[
            "회사 표준 배포 코드네임을 검색하고, echo 도구로 그 코드네임을 울려서 결과까지 보여줘."
        ],
        # text_contains 코드네임(codex 336 P2) — 도구명 카운트만으론 "아무거나 echo"도 통과.
        # 검색 사실이 최종 답까지 관통했는지를 토큰으로 고정(커버리지 축소 방지).
        expect=[
            ("rag_called",),
            ("tool_called", "echo", 1),
            ("text_contains", "SUITE-FACT-ALPHA-7743"),
            ("text_nonempty",),
        ],
    ),
    dict(
        key="pipeline-override-temperature",
        agent="pipeline",
        overrides={"temperature": 0.3},
        turns=["안녕이라고 답해줘."],
        expect=[("override_key", "temperature"), ("text_nonempty",)],
    ),
    # 노드형 회상은 노드별 프록시(268 P2) — trace.memoryRecalls(건수)로 단언(memories 표면과 다름).
    dict(
        key="pipeline-memory-recall",
        agent="pipeline",
        turns=["내 커피 취향을 반영해서 음료 하나만 추천해줘."],
        expect=[("memory_recall_min", 1), ("text_nonempty",)],
    ),
    # ── 조율형(스킬: orchestrate) — 위임 기록 + 오버라이드 대조 ──
    # 발견 실측 교정(289 P3): 후보 0의 주원인은 **미서빙**(스펙 256 게이트)이었다. lexical 탈락은
    # FirstMatch(orchestrate)에는 없고(첫 후보 무조건 위임) **orchestrate_ranked에만** 있다
    # (rank_candidates 겹침 0 제외 — 영숫자 토큰이 있는데 안 겹칠 때만, 한글-only=빈 쿼리 취급 통과).
    dict(
        key="orch-delegate",
        agent="orchestrate",
        turns=["suite-direct 에이전트에게 위임해서 답을 받아줘: 1 더하기 1은?"],
        expect=[("broker_min", 1), ("text_nonempty",)],
    ),
    dict(
        key="orch-override-nocaps",
        agent="orchestrate",
        overrides={"capabilities": []},
        turns=["suite-direct 에이전트에게 위임해서 답을 받아줘: 1 더하기 1은?"],
        expect=[("broker_zero",), ("override_key", "capabilities")],
    ),
    # 위임 0건 사유 표면화(스펙 289 P3) — 실행 후에라도 "왜"가 기록에 남는다(토큰만 쓰고 침묵 금지).
    dict(
        key="orch-unserved-reason",
        agent="orch_dead",
        turns=["suite-direct-bare 에이전트에게 위임해서 답해줘: 1 더하기 1은?"],
        expect=[("broker_zero",), ("graph_summary_contains", "위임 후보 0")],
    ),
    # ranked 전략: 영숫자 토큰("9999" 등)이 있는데 겹침 0이면 select 탈락 — 사유가 기록돼야 한다.
    dict(
        key="orch-ranked-no-match-reason",
        agent="orch_ranked",
        turns=["9999 곱하기 8888은 얼마야?"],
        expect=[("broker_zero",), ("graph_summary_contains", "선택 0")],
    ),
    dict(
        key="orch-memory-recall",
        agent="orchestrate",
        turns=["내 커피 취향이 뭐였지? 기억을 확인해서 답해줘."],
        expect=[("memory_hit", PREF_TOKEN)],
    ),
    # ── 분기형(스킬: route) — 결정적 분기("?" 유무)를 trace 타임라인으로 ──
    dict(
        key="route-branch-a",
        agent="route",
        turns=["대한민국의 수도는 어디야?"],
        expect=[("graph_node", "answer_a"), ("graph_node_absent", "answer_b")],
    ),
    dict(
        key="route-branch-b",
        agent="route",
        turns=["오늘 배운 내용을 두 문장으로 정리해 줘."],
        expect=[("graph_node", "answer_b"), ("graph_node_absent", "answer_a")],
    ),
    dict(
        key="route-memory-recall",
        agent="route",
        turns=["내 커피 취향이 뭐였지?"],
        expect=[("memory_hit", PREF_TOKEN), ("graph_node", "answer_a")],
    ),
    # ── 계획-실행형(스킬: plan_execute) ──
    dict(
        key="plan-tool",
        agent="plan",
        turns=["반드시 echo 도구를 호출해 'plan-288'을 돌려받아 결과를 알려줘."],
        expect=[("tool_called", "echo", 1)],
    ),
    dict(
        key="plan-rag",
        agent="plan",
        turns=[f"반드시 문서 검색 도구로 {KB_NAME}에서 회사 표준 배포 코드네임을 검색해 알려줘."],
        expect=[("rag_called",)],
    ),
]

# 노드 오버라이드(287) 커스텀 시나리오가 쓰는 상수 — run.py가 소유·참조.
NODE_OVERRIDE_TOKEN = "NODE-OV-288"
NODE_OVERRIDE_ECHO_PROMPT = f"반드시 echo 도구를 한 번 호출해 '{NODE_OVERRIDE_TOKEN}' 텍스트를 그대로 넣고, 결과를 전달하세요."
ECHO_TOOL = TOOL_ECHO

# ── 엣지 티어(스펙 290) — 단언은 "실패의 품질": 명확한 거절/정직한 축소, 조용한 오동작 금지. ──
EDGE_SCENARIOS: list[dict] = [
    dict(
        key="edge-historydepth-1",
        agent="bare",
        tier="edge",
        overrides={"historyDepth": 1},
        turns=[f"내 비밀 코드는 {SECRET}이야. 기억해 둬.", RECALL_PROMPT],
        expect=[("text_not_contains", SECRET), ("override_key", "historyDepth")],
    ),
    dict(
        key="edge-historydepth-typo",
        agent="bare",
        tier="edge",
        overrides={"historyDepth": "abc"},
        turns=["1 더하기 1은? 숫자만."],
        expect=[("text_nonempty",)],
    ),  # 형 가드(287) — 500 없이 저장값 폴백(실측)
    dict(
        key="edge-empty-content", agent="bare", tier="edge", turns=[""], expect=[("text_nonempty",)]
    ),  # 빈 입력=정상 턴(실측: 인사) — 500 금지
    dict(
        key="edge-unknown-override-key",
        agent="bare",
        tier="edge",
        overrides={"foo": "bar", "definitely_not_a_key": 1},
        turns=["1 더하기 1은? 숫자만."],
        expect=[("override_absent",), ("text_nonempty",)],
    ),  # allowlist 밖 키=무시
    dict(
        key="edge-deleted-delegate",
        agent="orchestrate",
        tier="edge",
        overrides={"capabilities": ["agt_nonexist290"]},
        turns=["위임해서 답해줘: 1 더하기 1은?"],
        expect=[("broker_zero",), ("graph_summary_contains", "위임 후보 0")],
    ),
]
SCENARIOS.extend(EDGE_SCENARIOS)
