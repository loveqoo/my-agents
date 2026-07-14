# 코드 품질 게이트(스펙 291) — `make metrics` 하나가 완료 판정자.
# 빠른 루프는 `make metrics-fast`(실모델 스위트 제외).

PY_SRC = packages/api/src packages/agent/src

.PHONY: lint format format-check complexity maintainability naming typecheck suite metrics metrics-fast sweep-debris sweep-debris-apply

lint:
	uvx ruff check $(PY_SRC)

# 네이밍 룰(스펙 292) — R1 bool 술어·R3 루프 변수 AST 감사(룰 원문은 docs/spec/292).
naming:
	uv run python scripts/naming_audit.py

format:
	uvx ruff format $(PY_SRC)

format-check:
	uvx ruff format --check $(PY_SRC)

# 블록 복잡도 상한 C(CC≤20) · 평균 A — radon 등급과 동일 산식(xenon=radon 게이트판).
complexity:
	uvx xenon --max-absolute C --max-average A $(PY_SRC)

# 유지보수성 지수: 전 파일 A(MI≥20) — B 이하가 하나라도 있으면 실패.
maintainability:
	@out=$$(uvx radon mi -n B $(PY_SRC)); \
	if [ -n "$$out" ]; then echo "$$out"; echo "FAIL: MI A 미만 파일 존재"; exit 1; fi; \
	echo "MI: 전 파일 A"

typecheck:
	uvx --with pydantic mypy $(PY_SRC)

# 실모델 조합 스위트(스펙 288/290) — 동작 불변의 최종 게이트.
suite:
	uv run python tests/suite/run.py

resource:
	uv run python tests/verify_347_resource_gate.py

metrics-fast: lint format-check complexity maintainability naming typecheck
	@echo "== metrics-fast 통과 =="

metrics: metrics-fast suite
	@echo "== metrics 전판 통과 =="

# 테스트 잔해 스윕(스펙 304) — 브라우저/verify 테스트가 라이브 DB에 남긴 에이전트 잔해 정리.
# dry-run은 무해(언제나 안전), apply는 비가역. 브라우저 샷 배치 후 재사용 teardown.
sweep-debris:
	uv run python tests/sweep_debris.py

sweep-debris-apply:
	uv run python tests/sweep_debris.py --apply
