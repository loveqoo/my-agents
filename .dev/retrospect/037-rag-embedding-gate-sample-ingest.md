# 037 — RAG 임베딩 게이트 + 샘플 적재 회고 (스펙 048)

마스터 044 배치4 · 어드민 테스트 피드백 #9("컬렉션이 전부 비어 고장처럼 보임").

## 무엇을 했나
1. **사용자 원칙을 게이트로 못박음** — "임베딩 모델 설정이 있는 경우만 적재, 임베딩 모델이 있을
   때만 RAG 메뉴 동작 가능". seed 컬렉션 시드를 `_collection_seed_specs(embs)`로 분리(embs=[]→[]),
   프론트는 `loaded && !models.length`로 배너+생성버튼 disabled, 백엔드는 유효 embedding id 없으면
   create 400(FK+kind). 서버 게이트가 진짜 enforced임을 verify로 잠금(chat/ghost id→400).
2. **대표 컬렉션 결정적 채움** — docs_kb를 mock-embed(`/_remote/v1/embeddings`, 1024 결정적)에
   바인딩해 라이브 MLX 없이 4개 헬프센터 샘플을 실 인제스트. 나머지 3개는 정직한 "비어있음" 플레이스홀더.
3. **멱등 스크립트** — `ingest_rag_samples.py`, 라이브 DB에 직접 실행해 어드민이 즉시 populated를 봄.

## 어디서 배웠나 (복리 지점)
- **learning 045 그대로 적용**: verify_048을 데모 시드에 결합 안 시키고 자체 mock-embed 모델+컬렉션
  (mdl_v048_/col_v048_)으로 self-fixture. 시드가 바뀌어도 통합 rung이 안 죽음. *과거 회고가 이번
  Context에서 즉시 적용된* 사례 — 인덱스 한 줄 후크로 끌어옴.
- **verification-ladder-three-rungs 적용**: 단위(게이트 헬퍼)+통합(실샘플 적재/검색, 실 DB)+적대
  리뷰. 셋이 안 겹침을 또 확인 — 단위·통합은 happy-path 초록인데 적대자가 #5(멱등 결함)를 잡음.

## 적대 리뷰가 잡은 것 — 다시 "방어를 깔았다 ≠ 작동한다"
셀프 검증 전부 GREEN(라이브 적재 4/4, 검색 OK) 뒤에서 적대 서브에이전트가 **CLAIM2를 반증**:
멱등성을 `doc_count>0`에 걸어 부분 실패를 "완료"로 오인(#5 MAJOR). 이건 retrospect 036에서 적은
바로 그 패턴의 재발이고, learning 041/044/046 메타패턴("서브유닛 방어는 전체를 못 묶는다")의
**WHICH-set 축**이었다 → learning 047로 박제. 수정: 파일명 단위 멱등(ready 스킵·error 재적재),
부분상태 자가치유를 *라이브로 실증*(1개 삭제→1개만 복구). 부수로 #1(삭제 500→409), #3(배너
플래시), #4(헬퍼 kind 방어), #8(tiebreak)도 같은 턴에 수정·재검증. 거짓 주장(spec의 "멱등")을
남기지 않으려 fast-follow 아닌 즉시 수정 — 045배치 테마가 "정직화"라 더더욱.

## 다음에 쓸 것
- 멱등/자가치유를 짤 땐 *완료 단위 집합*으로 판단(카운터 금지) — [[idempotency-on-success-counter-misses-partial]].
- "라이브 데모 비의존 결정성"이 필요하면 mock provider(`/_remote`) 바인딩이 견고한 패턴(스펙 024 철학).
- self-fixture는 이제 통합 검증의 기본값(045 이후 두 번째 적용).
