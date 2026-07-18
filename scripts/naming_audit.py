"""네이밍 컨벤션 감사(스펙 292) — R1(bool 술어)·R3(루프 변수) AST 카운터.

실행: `uv run python scripts/naming_audit.py [--list]` → 위반 0이면 exit 0, 아니면 1.
`make naming`으로 metrics-fast에 편입 — 룰은 docs/spec/292 참조.

R4 축약어 화이트리스트(참고 — 리뷰 게이트, 새 이름은 이 밖 축약 금지):
    cfg ctx db sess conn args kwargs exc err req resp msg impl env caps cap col cols
    doc mem uid pk ms i j + 도메인(mcp rag a2a hil rbac sse llm)
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOTS = ["packages/api/src", "packages/agent/src"]

# R1 — 판정 술어로 인정하는 형태 둘:
# ① 상태동사 토큰이 이름 어디든 **단어로** 존재 — 질문형 접두(is_valid_x)뿐 아니라
#    주어-동사형(host_is_private, resume_uses_memory, user_owns)도 잘 읽히는 술어다.
# ② 분사·형용사 어미로 끝남(permitted, drifted, delegable, empty …) — "~인가"로 읽힘.
STATIVE_VERBS = re.compile(
    r"(^|_)(is|has|can|may|should|supports|wants|allows|uses|owns|looks"
    r"|applies|matches|exists|contains|overlaps|survives|needs)(_|$)"
)
PREDICATE_ENDINGS = re.compile(
    r"(allowed|permitted|enabled|active|drifted|generating|served|remote|delegable"
    r"|blocked|valid|unreferenced|streaming|encrypted|private|empty|used|ready)$"
)
# R1 — 동작형(부수효과 있고 성공 bool 반환) 감사 화이트리스트: 술어 규칙 면제.
# 새 항목은 "부수효과가 실제로 있는가"를 확인하고 사유와 함께 추가한다.
ACTION_WHITELIST = {
    "add_policy",  # casbin 정책 추가 — 성공 여부 반환
    "remove_policy",  # casbin 정책 제거 — 성공 여부 반환
    "probe_endpoint",  # 원격 endpoint 실제 프로브(IO) — 도달 여부 반환
    "update",  # 메모리 백엔드 Protocol — 기억 수정(부수효과), 성공 반환
    "delete",  # 〃 — 기억 삭제
    "update_memory",  # 메모리 파사드 — update 위임
    "delete_memory",  # 〃 — delete 위임
    # 스펙 386 등재 4건 — 전부 실부수효과+성공 bool 확인:
    "record_block_version",  # 블록 이력 append+version 증가(스펙 369) — "버전이 올랐는가" 반환
    "_acquire_reindex_lock",  # 컬렉션 status→reindexing UPDATE(배타 잠금 획득) — 획득 여부 반환
    "_try_become_leader",  # pg advisory lock 획득+커넥션 보유(스펙 348) — 리더 여부 반환
    "reload_schedules",  # 스케줄러 잡 재구성(cron 즉시 반영, 스펙 348) — 리더로 반영했는가 반환
    "_start_auto_run",  # 자동 회귀 단건 시작(스펙 399) — EvalRun commit+spawn(실부수효과), 시작 여부 반환
}


def _is_predicate_name(name: str) -> bool:
    bare = name.lstrip("_")
    return bool(STATIVE_VERBS.search(bare)) or bool(PREDICATE_ENDINGS.search(bare))


def _iter_python_files() -> list[Path]:
    return [path for root in ROOTS for path in Path(root).rglob("*.py")]


def _comprehension_targets(tree: ast.AST) -> set[int]:
    """컴프리헨션 내부 for 타깃의 위치(줄·열) — R3 예외(한 줄 스코프)라 블록 for와 구분."""
    spots: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for comp in node.generators:
                for target in ast.walk(comp.target):
                    if isinstance(target, ast.Name):
                        spots.add(id(target))  # 같은 트리 안이므로 노드 identity로 충분
    return spots


def audit(list_violations: bool = False) -> int:
    r1: list[str] = []  # bool 반환인데 술어형도 동작 화이트리스트도 아님
    r3: list[str] = []  # 블록 for문의 한 글자 타깃(i·j·_ 제외)
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        comp_targets = _comprehension_targets(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                returns = node.returns
                if (
                    isinstance(returns, ast.Name)
                    and returns.id == "bool"
                    and not _is_predicate_name(node.name)
                    and node.name not in ACTION_WHITELIST
                ):
                    r1.append(f"{path}:{node.lineno} {node.name}")
            if isinstance(node, (ast.For, ast.AsyncFor)):
                target = node.target
                if (
                    isinstance(target, ast.Name)
                    and len(target.id) == 1
                    and target.id not in {"_", "i", "j"}
                    and id(target) not in comp_targets
                ):
                    r3.append(f"{path}:{node.lineno} for {target.id}")
    total = len(r1) + len(r3)
    print(f"R1 bool 술어 위반: {len(r1)} · R3 한 글자 루프 변수: {len(r3)} → 총 {total}")
    if list_violations:
        for line in r1:
            print(f"  R1 {line}")
        for line in r3:
            print(f"  R3 {line}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(audit(list_violations="--list" in sys.argv))
