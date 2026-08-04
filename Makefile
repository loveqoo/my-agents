# 코드 품질 게이트(스펙 291) — `make metrics` 하나가 완료 판정자.
# 빠른 루프는 `make metrics-fast`(실모델 스위트 제외).

PY_SRC = packages/api/src packages/agent/src

.PHONY: lint format format-check complexity maintainability naming typecheck suite metrics metrics-fast sweep-debris sweep-debris-apply clean-test-agents clean-test-agents-apply reset-dev reset-dev-yes test test-unit test-all e2e perf-build

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

# 회귀망(스펙 353) — 흩어진 verify_*.py를 상시 그물로. 통과분만 그물, 드리프트는 명시 격리.
test:               # 씨앗 그물: unit+db(상태 격리 가능·빠름). 그물 전부 통과면 exit 0.
	uv run python tests/run_suite.py
test-unit:          # 순수층만(무의존·병렬·최속)
	uv run python tests/run_suite.py unit
test-all:           # 전층(http 포함 — dev 서버 8000 전제. http는 상태 오염 취약, 참고용)
	uv run python tests/run_suite.py all
test-browser:       # 브라우저 verify 그물(스펙 438) — vite+api+playwright 전제, 수십 분. 격리 목록은 러너 안.
	uv run python tests/run_browser_suite.py

perf-build:         # 빌드 핫패스 베이스라인(스펙 368) — 전제: 실서버 8000(계측 포함 코드).
	uv run python tests/measure_build_hotpath.py

e2e:                # E2E(Playwright): api(Bearer)+admin/mobile(브라우저) 전수. 전제 API(8000)+Postgres.
	@echo "== E2E: API(8000) 가동 전제. vite(5173)는 없으면 자동 기동, 인증은 global-setup 쿠키 로그인 =="
	cd tests/e2e && npx playwright test

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

reset-dev:           # dev 초기화 계획만 출력(무해) — 절차·함정은 scripts/reset_dev.py 헤더
	uv run python scripts/reset_dev.py

reset-dev-yes:       # 실제 초기화(파괴적): 정지→DB drop→재기동→실모델 복원→검증 일괄
	uv run python scripts/reset_dev.py --yes

clean-test-agents:   # 도그푸딩 DB의 테스트-누수 에이전트 dry-run(시드 데모는 KEEP)
	uv run --package api python tests/clean_test_agents.py

clean-test-agents-apply:  # 실제 삭제(정식 API 삭제 관문 경유)
	uv run --package api python tests/clean_test_agents.py --apply
