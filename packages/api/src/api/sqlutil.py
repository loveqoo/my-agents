"""SQL 조립 유틸(정본, 스펙 298) — route/backend 어디서나 의존 없이 쓰는 순수 함수."""


def like_escape(term: str) -> str:
    """LIKE/ILIKE 리터럴화 — 사용자 입력의 `\\`·`%`·`_`를 이스케이프한다.

    와일드카드 오라클/과매칭 차단(세션 098). 호출부는 `.ilike(f"%{like_escape(q)}%", escape="\\")`로
    쓴다. 순수 문자열 함수라 홈에 DB 의존이 없어 leaf backend(mem0)도 route 모듈을 끌어오지 않는다.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
