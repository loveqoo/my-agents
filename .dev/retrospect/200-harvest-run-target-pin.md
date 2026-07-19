# 200 — 수확 실행 대상 고정(스펙 209 보완)

> **복원 노트**: 이 파일은 인덱스 줄만 있고 full 파일이 생성되지 않았던 항목을 INDEX 후크에서 복원한 것이다(스펙 400 verify_043 실측 — 같은 턴 파일 생성 누락). 원 세션의 상세 서사는 유실됐고, 아래는 후크가 보존한 전부다.

수확 실행 대상 고정(스펙 209 보완) — 사용자가 잡음: 수확 문제집이 실행 시 에이전트 미고정, source_agent_pk를 읽기게이트에만 쓰고 실행 대상 배선을 빠뜨림(FK 저장≠목적까지 배선), RAG collection_id 고정 선례 미적용 발견 → 브라우저e2e

키워드: stored-fk-not-wired-to-purpose,apply-existing-precedent,feature-purpose-is-default
