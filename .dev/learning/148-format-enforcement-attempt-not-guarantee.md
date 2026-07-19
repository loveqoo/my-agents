# 148 — 신뢰 못 할 생산자 위 "형식 강제"는 보장이 아니라 시도+정직한 실패로 짜라

> **복원 노트**: 이 파일은 인덱스 줄만 있고 full 파일이 생성되지 않았던 항목을 INDEX 후크에서 복원한 것이다(스펙 400 verify_043 실측 — 같은 턴 파일 생성 누락). 원 세션의 상세 서사는 유실됐고, 아래는 후크가 보존한 전부다.

신뢰 못 할 생산자 위 "형식 강제"는 보장이 아니라 시도+정직한 실패로 짜라 — structured-output 미보장 환경(mock)에서 실패하면 거짓 형식 짓지 말고 원문 통과(가짜 성공 은폐 금지); 강제 개입은 최종 응답에만

키워드: format-enforcement,untrusted-producer,attempt-not-guarantee,honest-fallback-no-fabrication,pass-through-original-not-repair,intervene-on-final-response,lenient-extractor-trust-boundary,fake-model-scripted-verify
