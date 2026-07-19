# 147 — 누적 상태 위 "격리/리셋"은 도구 루프·재진입까지 위협모델에 넣어라

> **복원 노트**: 이 파일은 인덱스 줄만 있고 full 파일이 생성되지 않았던 항목을 INDEX 후크에서 복원한 것이다(스펙 400 verify_043 실측 — 같은 턴 파일 생성 누락). 원 세션의 상세 서사는 유실됐고, 아래는 후크가 보존한 전부다.

누적 상태 위 "격리/리셋"은 도구 루프·재진입까지 위협모델에 넣어라 — 입력 조립만 바꾸면 ToolNode가 누적에 append해 재진입이 옛 대본을 다시 봄(재-오염); RemoveMessage로 실제 제거해야 진짜 격리

키워드: isolation-on-accumulated-state,tool-loop-reentry,repollution,removemessage-reset,graph-topology-signal,record-received-messages,behavior-not-structure,lifecycle-guard-sibling
