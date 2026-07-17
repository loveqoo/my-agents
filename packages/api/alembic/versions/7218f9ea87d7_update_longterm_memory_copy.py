"""장기 기억 블록 문구를 스펙 387 실동작 서술로 갱신(문구 화석 부활 봉합).

c1d2e3f4a5b6의 데이터 시드가 032 이전 문구("요청 userId로 자동 결정")를 INSERT해 fresh DB마다
옛 문구가 부활했다(회고 391의 문구판 — 행 삭제와 같은 부류). 체인 끝 UPDATE로 fresh/기존 DB의
최종 문구를 seed.py 현행과 일치시킨다.

Revision ID: 7218f9ea87d7
Revises: 40079d14052f
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "7218f9ea87d7"
down_revision: Union[str, Sequence[str], None] = "40079d14052f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCOPE = "유저 단위 · 머신은 userId 지정 시"
_BODY = (
    "mem0 장기 메모리. 켜면 대화에서 사실을 추출·저장하고 매 턴 의미적으로 유사한 top-k를 회상합니다. "
    "로그인 사용자와의 대화는 유저 단위로 세션을 넘어 기억합니다. 머신/A2A 호출은 userId를 함께 "
    "보내면(스펙 387) 그 유저 단위로 똑같이 기억하고, 없으면 이번 대화(세션)에만 유지합니다."
)


def upgrade() -> None:
    op.execute(
        "UPDATE memory_types SET scope = '" + _SCOPE.replace("'", "''") + "', "
        "body = '" + _BODY.replace("'", "''") + "' WHERE name = '장기 기억 (mem0)'"
    )


def downgrade() -> None:
    # c1d2e3f4a5b6 시드 문구로 복원(대칭).
    op.execute(
        "UPDATE memory_types SET scope = 'Auto · userId 유무로 결정', "
        "body = 'mem0 장기 메모리. 켜면 대화에서 사실을 추출·저장하고 매 턴 의미적으로 유사한 top-k를 회상합니다. "
        "스코프는 요청 userId로 자동 결정 — userId가 있으면 유저 단위(세션 가로지름)와 세션에 함께 저장하고, "
        "없으면 현재 세션에만 저장합니다.' WHERE name = '장기 기억 (mem0)'"
    )
