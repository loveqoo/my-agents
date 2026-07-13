# 306 — RAG 문서 런타임 수정 + 부분 재임베딩 (스펙 331)

## 무엇을 했나

문서형 컬렉션의 문서를 admin에서 직접 수정(CodeMirror, 확장자 인식 하이라이트) → 저장하면 그
문서만 재청킹하고 **내용 동일 청크는 벡터 재사용·변경 청크만 재임베딩**. 스펙 312의 blob 시임이
두 번째로 회수된 사례(재인덱싱→문서 편집, 새 저장 구조 0·검색 무중단 승계).

## 핵심 배운 것

### 1) 집계 증분은 스냅샷 값이 아니라 그 트랜잭션의 실측으로
컬렉션 chunk_count 증분을 `- doc.chunk_count + len(new)`로 썼는데, doc.chunk_count는 임베딩
HTTP 전에 읽은 스냅샷(expire_on_commit=False라 커밋 후에도 stale) — 동시 편집이면 집계가 어긋난다
(codex P1). **스왑 트랜잭션 안에서 delete rowcount로 계산**하면 각 PUT의 델타가 자기 실측이라
순서와 무관하게 정합. "합의된 기준값 대비"가 아니라 "지금 지운 만큼"이 정직하다.

### 2) 통계 불변식은 호출 축과 집계 축을 분리해야 지켜진다
임베딩 호출은 유일화(같은 텍스트 1회)하고 통계도 그 len을 쓰니, 중복 신규 청크에서
reused+reembedded==chunks가 깨졌다(codex P2). 통계=occurrence 기준(청크 수), 호출=유일화 —
같은 데이터의 두 관점을 한 변수로 겸용하면 경계 사례가 계약을 부순다.

### 3) 파싱 뒤 len 검사는 크기 상한이 아니다 — [[cap-the-raw-source-not-the-buffer]] 재확인
PUT body 상한을 Pydantic 파싱 후 len(data)로만 걸었더니 "이미 메모리에 올라온 뒤"(codex P2).
Content-Length 선검사 의존성으로 파싱 전 차단 + chunked 우회는 정직 경계로 주석·OUT(인증 admin
표면). 상한은 최대한 원류에서.

### 4) antd v6에서 e2e 셀렉터·컴포넌트 관용구 둘 다 드리프트
- Drawer 내부 클래스가 `.ant-drawer-content`→`.ant-drawer-section`(셀렉터가 조용히 0건 매칭 —
  "제목 텍스트는 보이는데 컨테이너가 없다"가 신호였고 DOM 덤프가 30초에 결론).
- `maskClosable`은 v6 deprecated(`mask.closable`) — admin 규칙(새 코드 deprecated 금지) 준수.
- 새 컴포넌트에서 `App.useApp()`을 썼더니 **토스트가 조용히 무동작**(admin은 <App> 프로바이더
  없음, 레포 관용구는 정적 `message`) — 새 파일일수록 이웃 파일의 관용구부터 확인.

### 5) 결정적 mock 임베딩의 "순위"는 무작위다
G7을 유사 문구 질의로 썼다가 top-1이 엉뚱한 청크 — mock 벡터는 sha256 시드라 동일 텍스트만
결정적(코사인 1.0), 유사 문구 간 순위는 의미 없음. 검색 반영 단언은 **동일 텍스트 질의**로
결정화. 반대로 e2e는 dev DB가 실모델(e5)이라 임계를 느슨히(핵심 단언=최상위가 수정 문단).

## 검증
- VERIFY331_OK 19/19(virgin DB) — 부분 재임베딩은 **embed_texts 캡처**로 실증(변경 청크만 전송):
  결정적 mock이라 벡터 동일성 비교는 재사용 증명력이 0이기 때문.
- VERIFY331_UI_OK — 로그인→편집→저장 토스트(재임베딩 1·재사용 1)→GET content 왕복→검색 최상위.
- 312/313/329 무회귀(312 1건 실패=stash 확증 기존 드리프트) · codex P1/P2 0(수정 후).

관련: [[cap-the-raw-source-not-the-buffer]] · 스펙 312(blob 시임 원형)·313(무중단)·192(전체화면
Modal 선례) · 회고 303("시임은 갈아탈 때 회수" — 이번엔 기능 확장에서 회수)
