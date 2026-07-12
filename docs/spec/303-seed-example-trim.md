# 303 — 첫 설치 시드 예제 트림(최소 정예)

## 배경

"프로젝트 처음 설치 후 보이는 예제가 정돈되지 않았다"(사용자). 조사 결과 두 층이 섞임:
- **테스트 잔해(별개)**: 현재 dev DB 에이전트 58개 중 53개가 verifier/브라우저 테스트 산물(pipeline-*/
  rt-*/node-insp-* 등). **신선 설치엔 없음**(seed 아님) — 이번 스코프 밖(사용자 선택).
- **시드 예제(이번 대상)**: `seed_if_empty`가 심는 진짜 첫 설치 데이터. 여기에 고아·빈 데모가 섞여 있음.

사용자 결정: **최소 정예(트림)** — 고아·빈 데모를 걷어내고 꼭 필요한 대표만 깔끔하게.

## 현재 시드 인벤토리 (조사)
- 에이전트 5: research-assistant(ui·RAG·MCP·mem0)·personal-secretary(ui)·plan-execute-demo(커스텀 flow)·
  doc-translator(code)·acme-translate-a2a(external) — **각자 다른 source/능력, 고아 없음**.
- 페르소나 4 중 **2 고아**: strict-senior-engineer·calm-sre(스펙 046서 Code Reviewer/Ops Copilot 제거되며
  남음, 실 참조 0 — test 산출물 scorecard.json 언급뿐).
- 컬렉션 4: docs-kb(샘플·research가 씀)·product-titles(빈·research가 씀)·team-notes(빈·secretary가 씀)·
  **support-tickets(빈·아무도 안 씀=고아)**.
- 세션 4: 전부 turns=0·Message 행 없음(채널/상태 다양성용 빈 껍데기).
- 승인 0(이미 비어 있음).

## 트림 (측정 가능)
1. **페르소나 4→2**: strict-senior-engineer·calm-sre 제거(고아). methodical-researcher·warm-secretary 유지.
2. **컬렉션 4→3**: support-tickets 제거(고아). docs-kb·product-titles·team-notes 유지(에이전트 vectorTables
   참조 유지 — 제거하면 에이전트 RAG 배선이 깨짐).
3. **세션 4→0**: 빈 껍데기 제거 → 첫 설치 세션 화면은 **정직하게 빈 상태**로 시작(실사용으로 채워짐).
   "화면이 빈 상태가 아니라 의미있는 데이터로"(seed 도크) 원칙과 정합 — 빈 세션은 의미 데이터가 아님.
4. **에이전트 5 유지**: 트림 대상 아님(고아·빈 없음, 각자 대표성). 이름·설명 이미 일관(kebab·Title Case).
5. **시드 도크 주석 정정**: "admin/src/admin/mockData.ts 와 동일한 도메인 데이터"는 이미 어긋남(세션
   turns seed=0 vs mockData=6/14/21) + mockData 데이터 배열은 死코드(21파일이 타입·상수만 import).
   → seed.py를 실 DB 첫 설치의 **단일 출처**로 명시하고 mockData 미러 문구 제거.

## OUT (이번 스코프 밖)
- 테스트 잔해(53 에이전트 등) 정리 — 별개(dev DB 청소·테스트 teardown 개선), 신선 설치 무관.
- mockData.ts 死데이터 배열 제거 — 렌더 안 되지만 파일은 타입/상수로 살아있음. 별도 후속(타입·상수 보존
  하며 데이터 배열만 제거는 세심한 분리 필요).
- 에이전트 수 증감(쇼케이스 보강은 A안, 사용자가 B 트림 선택).

## 검증
- **데이터 정합(단위)**: 트림 후 seed 정합 — 참조 무결(에이전트 vectorTables/persona가 가리키는 자산
  전부 존재), 고아 0(페르소나·컬렉션 전부 ≥1 에이전트 참조 또는 의도적 대표). 스크립트로 측정.
- **신선 시드 스모크**: 빈 테스트 DB에 seed_if_empty → 심긴 카운트 확인(페르소나 2·컬렉션 3·세션 0·
  에이전트 5·승인 0). dev DB는 이미 시드됨이라 무영향(seed_if_empty는 비어있을 때만).
- **부팅 무회귀**: seed import·metrics-fast 0. 브라우저로 첫 설치 화면 확인은 재시드 필요(사용자와 합의).

## 노트
- seed는 **빈 DB에만** 실행 → 현재 오염 dev DB엔 이번 변경이 반영 안 됨. 트림 결과를 화면으로 보려면
  재시드(DB 초기화) 필요 — 파괴적이라 사용자 명시 시에만.
