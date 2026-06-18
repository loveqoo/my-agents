# 001 — 미니멀 하드코딩 에이전트 (실행계획)

상태: **검토 대기**
날짜: 2026-06-19
지배 스펙: [docs/spec/001-system-overview.md](../../docs/spec/001-system-overview.md) 의 **첫 실행 증분**

> 목적: 001 시스템을 처음으로 한 줄 돌려보는 "걷는 뼈대". 버릴 코드가 아니라 뼈대의 시작.

---

## 목표
- **코드에 하드코딩된 단일 에이전트**가 로컬 MLX 모델과 **순수 대화**한다.
- **CLI**로 실행해 동작을 눈으로 확인한다.

## 범위

### 들어가는 것
- 최소 uv 프로젝트 1개
- 하드코딩 에이전트: 페르소나(시스템 프롬프트) + 모델 설정
- LangGraph **단일 ReAct** 그래프 (`tools=[]`)
- CLI 대화 루프

### 빠지는 것 (이 증분 제외)
- SPA, DB/Postgres, 모델 등록·관리, MCP(소비/노출), Mem0 메모리, 체크포인터, A2A, Langfuse

---

## 확정 결정
| 항목 | 값 |
|---|---|
| 진입점 | CLI 스크립트 (`uv run`) |
| 툴 | 없음 (순수 대화) |
| 에이전트 정의 | 코드 하드코딩 (페르소나 + 모델) |
| 모델 | `mlx-community/Qwen3.6-35B-A3B-mxfp8` (로컬 MLX, OpenAI 호환) |
| 엔드포인트 | `http://localhost:8045/v1` |
| 인증 | Bearer 키 — **환경변수**(`MLX_API_KEY`), 코드/리포에 하드코딩 금지 |

## 전제
- 로컬 MLX 서버가 `localhost:8045`에 떠 있고 위 모델이 로드돼 있음. (2026-06-19 연결·chat 응답 확인 완료)

---

## 제안 구조 (uv 워크스페이스 + 모듈 1개)
```
my-agents/
  pyproject.toml                 # uv 워크스페이스 루트 (members = ["packages/*"])
  .env.example                   # MLX_BASE_URL, MLX_API_KEY, MLX_MODEL
  packages/
    agent/                       # 지금 만드는 패키지 1개
      pyproject.toml             # 패키지 메타 + CLI script 엔트리
      src/agent/
        __init__.py
        main.py                  # 모듈 1개: 하드코딩 에이전트(ChatOpenAI+ReAct) + CLI 루프
```
> 001의 `packages/{core,mcp,memory,api}`는 **이후 증분에서** 추가. 지금은 워크스페이스 골격 + `agent` 패키지 1개 + 모듈 1개만.

## 의존성 (예상)
- `langgraph`, `langchain-openai`, `langchain-core`, `python-dotenv`(선택)

---

## 실행 단계
1. uv 워크스페이스 루트 `pyproject.toml` 작성(members=packages/*) + `.env.example`.
2. `packages/agent` 패키지 생성(pyproject + CLI script 엔트리) + 의존성 추가.
3. `src/agent/main.py`: `ChatOpenAI(base_url, api_key=env, model)` → `create_react_agent(model, tools=[], prompt=PERSONA)` + stdin 대화 루프.
4. 로컬 MLX 상대로 `uv run` 실행 검증.

## 검증 (완료 기준)
- [ ] `uv run`으로 CLI 실행 → 질문 입력 → **일관된 한국어 답변** 수신 (예: "한국의 수도?" → 서울).
- [ ] API 키가 코드/리포에 노출되지 않음 (env 경유).

## 위험 / 메모
- **Qwen thinking 출력:** 모델이 응답 앞에 사고 과정을 그대로 뱉음("Here's a thinking process…").
  - 대응 후보: OpenAI 호환 `extra_body`로 thinking 비활성(`enable_thinking: false` 류) 시도, 또는 응답에서 reasoning 분리.
  - 실행 중 확인해 처리. 막는 요인은 아님.
- 검증은 로컬 MLX 가동에 의존 — 서버가 꺼져 있으면 실행 불가.

## 회고로 넘길 것 (Compounding 시)
- "재촉하지 말 것"(매 턴 승인/커밋/다음으로 몰지 않기) 학습화. → `.dev/learning/`
