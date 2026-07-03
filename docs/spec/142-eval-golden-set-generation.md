# 142 — 평가 6탄: 골든셋 자동 생성 (컬렉션 → RAG 문제집)

## 배경 / 왜
조사(learning 141): "골든셋이 없어서 IR 지표를 못 쓴다"는 틀린 전제 — Ragas/DeepEval은 문서에서
테스트셋을 자동 생성한다. 현재 최대 마찰 = 문제를 손으로 만들어야 함. v1은 **단일 청크 기반**
(Ragas 지식그래프식 멀티홉은 OUT — 후속 확장축).

## 설계
1. **생성기(eval_golden.py)**: `generate_golden_cases(collection, count, llm_cfg)` —
   - 청크 표본: 컬렉션에서 랜덤 N×2개 후보(문서 다양성 위해 문서별 최대 2청크), 너무 짧은
     청크(<80자) 제외.
   - 청크당 기본 chat 모델(temp 0.3)로 "이 문단만으로 답할 수 있는 자연스러운 한국어 질문 1개"
     생성 — **엄격 형식(첫 줄=질문만), 형식 이탈·중복 질문은 그 청크 건너뜀**(fail-closed 카운트).
   - 케이스 자동 기준: `rag_source_contains(그 청크의 문서 파일명)` + `rag_hits_gte 1` + `no_error`
     — "생성 질문으로 검색하면 출처 문서가 나와야 한다"는 자기일관 골든.
   - count 달성 또는 후보 소진까지. 반환: [{question, filename}]+skipped 수.
2. **API**: `POST /eval/generate-dataset` {collection_id, name, count(1~20)} — admin.
   즉시 EvalDataset(kind=rag, description="생성 중…") 생성·반환 → **백그라운드**로 케이스 생성
   (러너와 같은 create_task 패턴), 완료 시 description="자동 생성 M건(요청 N, 건너뜀 k)".
   실패 시 description에 오류 박제(조용한 빈 문제집 금지). 시작 시 좀비 대비: 서버 재시작
   sweep은 불필요(문제집은 남고 description이 "생성 중…"이면 재생성 안내 — 정직 표기).
3. **UI**: 문제집 탭에 "컬렉션에서 생성" 버튼 → 모달(컬렉션 Select·개수·이름 자동 제안) →
   생성 후 목록에 등장, 드로어에서 문제 확인·수정(기존 편집기). description 상태 표시.
4. **품질 신호**: 생성된 문제집을 그 컬렉션으로 **바로 실행하면 self-consistency 점수**가 나온다
   (출처 문서가 실제로 검색되는가) — 통합 검증에서 이 점수로 생성 품질을 측정.

## 검증
- 단위: 질문 형식 파서(첫 줄·이탈 거부)·짧은 청크 제외·중복 건너뜀·count 범위(0/21 → 422).
- 통합(실 Obsidian): count 3 생성 → 케이스 3건·기준 3종 자동 부여 → **그 문제집 실행 →
  score ≥ 2/3**(self-consistency — 생성 질문이 출처를 되찾는가). 오염: 세션/mem0 불변.
- e2e(fast-worker): 모달→생성→문제 채워짐→실행→성적표. codex 간이.

## 비목표 (OUT)
- 멀티홉/추상 질문(지식그래프), 정답(expected) 텍스트 생성(질문+출처만 — expected 1급 필드는
  별도 스펙), 진화(evolution)·critic 필터, 비-rag(agent) 문제집 생성.
