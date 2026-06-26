# 033 — alembic autogenerate는 metadata에 없는 "남의 테이블"을 drop하려 든다

지배 스펙: [docs/spec/031](../../docs/spec/031-multi-user-auth-and-pluggable-providers.md) · 날짜: 2026-06-26

## 증상

스펙 031에서 `user`/`accesstoken`/`roles` 테이블 추가 후 `alembic revision --autogenerate` 하니,
upgrade에 우리가 의도한 `create_table` 3개와 **함께** `op.drop_table('mem0_memories')` +
인덱스 drop이 끼어 있었다. downgrade엔 그 테이블 recreate가 들어갔다.

## 원인

autogenerate는 **DB 실제 스키마 ↔ SQLAlchemy `Base.metadata`**를 비교한다. `mem0_memories`는
**Mem0 런타임이 자기 손으로 만든 테이블**이라 우리 ORM `Base`에 매핑이 없다 → autogenerate 눈엔
"metadata엔 없는데 DB엔 있는 테이블" = 삭제 대상으로 보인다. 우리 소유가 아닌데 drop 코드가 생성된다.

## 교훈 / 대응

- **autogenerate 산출물은 초안일 뿐, 그대로 믿지 말 것.** upgrade/downgrade 둘 다 읽고 *우리가
  의도한 변경만* 남긴다. 특히 `drop_table`/`drop_index`는 한 줄씩 출처 확인.
- 외부 런타임(Mem0·확장·다른 서비스)이 만든 테이블은 손대지 않는다 — 삭제 op는 제거하고
  "이 테이블은 X가 관리, 우리 소유 아님" 주석을 남겼다. ("지우기 전에 대상을 본다" 규칙과 동일.)
- 항구 대책 후보(미적용): autogenerate `include_object` 훅으로 외부 테이블을 비교에서 제외하면
  애초에 drop이 안 나온다. 외부 테이블이 늘면 도입 고려.

## 관련

- 동일 사건의 회고: [.dev/retrospect/022](../retrospect/022-multi-user-auth-fastapi-users-casbin.md)
