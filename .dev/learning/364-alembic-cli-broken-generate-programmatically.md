# 364 — 이 레포는 alembic CLI가 순환 임포트로 깨진다·마이그레이션은 프로그램적으로

## 사건

스펙 364에서 컬럼 3개를 추가하려 `uv run alembic heads`/`revision --autogenerate`를 돌렸더니
`ImportError: cannot import name 'SQLAlchemyBaseUserTableUUID' from 'fastapi_users.db'`로 실패.
그런데 그 심볼은 실제로 존재하고(`dir(fastapi_users.db)`에 있음) `import api.models`도 단독으론 성공.

## 원인 — CLI 컨텍스트의 순환/부분초기화

"cannot import name X from Y"는 X 부재가 아니라 **Y가 부분초기화**됐다는 신호다. alembic CLI가 버전
파일들을 로드할 때 오래된 마이그레이션(`b2c3d4e5f6a7`)이 `from api.models import RAG_EMBED_DIMS`로
api.models를 **재-임포트**하는데, 그 시점 fastapi_users가 아직 초기화 중이라 순환이 터진다. 앱 부팅은
이 경로를 안 타서(모델이 이미 완전 로드된 뒤 lifespan에서 `command.upgrade`) 멀쩡하다.

## 처방 — 프로그램적 생성/적용 (앱 lifespan과 동일 경로)

CLI를 고치려 하지 말고, `api.models`를 **먼저 완전 로드**한 뒤 alembic을 프로그램적으로 부른다:

```python
import sys; sys.path.insert(0, "src")
import api.models                      # 완전 로드 → 이후 재-임포트는 sys.modules 히트(순환 없음)
from alembic import command
from api.db import _alembic_config     # 앱과 같은 Config(ALEMBIC_EMBEDDED=1)
command.revision(_alembic_config(), message="...", autogenerate=True)   # 생성
command.upgrade(_alembic_config(), "head")                              # 적용
```

DB 측정은 psycopg2 미설치라 URL을 `+psycopg`로 바꿔 `create_engine`(inspect로 컬럼/인덱스 실재 확인).

## 함께 상기할 것

- **autogenerate는 런타임 소유 객체를 대량으로 지우려 든다** — checkpoints·mem0_memories·casbin_rule은
  langgraph·mem0·casbin이 런타임에 만들어 우리 metadata 밖이라, autogenerate가 `drop_table`로 제안한다.
  무관 인덱스 churn(agents unique·rag_chunks hnsw 등)도 함께. **생성물은 반드시 손으로 트림**해 의도한
  변경만 남긴다("please adjust!"는 빈말이 아니다). [[hand-authored-migration-ids-collide-silently]]의
  자매 함정 — 그건 id 충돌, 이건 스코프 오염.
- 리비전 id는 CLI가 못 붙이니 프로그램적 생성이 랜덤 hex를 붙여준다(손수 순번 금지 계열 자동 충족).
- 서버가 `--reload`가 아니면 모델 편집이 반영 안 되므로, 마이그레이션 적용 후 **API 재기동**해야 새
  컬럼을 코드가 쓴다([[user-is-remote-do-host-actions-yourself]] — 내가 직접 재기동).
