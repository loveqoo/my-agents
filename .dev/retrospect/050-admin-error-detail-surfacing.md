# 050 — Admin API 에러 `detail` 가시화 + RAG 차원 불일치 조치 안내 (스펙 062)

> 단독 스펙. 실제 버그 레포트(사용자 스샷): "Admin > RAG 컬렉션 생성 시 POST /collections가
> '→ 409'만 보여 원인 파악 불가". 선행 자산: learning 063(fail-closed 가드 메시지 3요소)·062(cap-the-raw-source).

## 무엇을 했나

증상은 하나("→ 409만 보임")였지만 코드재현(probe-deeper, 추측금지)으로 **두 결함**을 갈랐다:

- **(A) 근본·전역**: 백엔드는 *이미* 사유를 `HTTPException(detail=…)`에 담는데(`_dim_mismatch`:
  "출력 차원(4096)이 저장소 차원(1024)과 다릅니다…", 중복이름: "같은 이름의 컬렉션이 이미 있습니다."),
  프런트 **중앙 헬퍼 `j()`가 본문 `detail`을 버리고 `throw new Error(… → ${status})`로 상태코드만**
  던졌다. CollectionsView는 `message.error(e.message)`로 "서버 메시지를 그대로 노출"하려 *의도*하고
  주석까지 그렇게 적었지만, 중앙 헬퍼가 그 메시지를 이미 뭉개버려 사용자에겐 "→ 409"만 닿았다.
  `j()`를 쓰는 **모든 화면 공통** 결함.
- **(B) 백엔드 메시지 결핍**: 차원 불일치 사유에 *조치(어떻게)*가 빠져 learning 063의 3요소(무엇·왜·
  어떻게) 中 하나 결핍.

처방: **D1** `admin/src/httpError.ts` 중앙 추출(본문에서 `detail` 한 필드 문자열만 꺼냄·제어문자 제거·
길이 상한·없으면 `METHOD path → status` 폴백), `j()`·`uploadDocument`·`streamChat`에 적용.
**D2** `_dim_mismatch`에 조치 한 줄 추가("{target}차원 모델을 선택하거나, 관리자에게 정책 변경 요청").
**D3** CollectionsView는 이미 `e.message`라 무변경(D1이 메시지를 채움).

## 핵심 통찰

1. **큐레이션된 서버 메시지는 전송/경계 계층이 버리면 무용지물이다.** 백엔드는 *정직하게* 안전한
   사유를 만들어 내려보냈고(every `detail` = 안전 문자열), 표시단(CollectionsView)도 그걸 보여줄
   준비가 돼 있었다 — 그런데 그 사이 **중앙 fetch 경계가 body→status로 뭉개** 가치를 0으로 만들었다.
   생산자와 소비자가 둘 다 옳은데 *둘이 만나지 못한다*. 그래서 고칠 곳은 끝단 N개가 아니라 **가치를
   버리던 그 중앙 경계 한 곳**(`j()`→`httpError`)이고, 한 곳을 고치니 전역 복구됐다. → learning 065.

2. **codex가 1차로 잡은 Medium이 *내가 이미 가진 learning의 안티패턴 그 자체*였다.** `httpError`
   초안은 본문을 통째 `res.json()`으로 파싱한 *뒤* 600자로 잘랐다 — 상한을 *버퍼 위에* 건 것.
   이건 learning 062(cap-the-raw-source)가 "막은 척"이라 명시한 바로 그 패턴이다. 거대/무한 본문은
   parse/decode 단계에서 이미 메모리·시간을 먹는다. 적대자(codex)가 `{"detail":"A"×5e8}`로 구체화.
   → 본문을 ReadableStream으로 **raw 바이트 누적·상한(64KB)**, 안 끝나는 스트림(SSE 에러 hang, codex
   Low)은 **시간 상한(5s)**으로 끊고 reader cancel. 같은 경계가 두 결함을 동시에 막았다. 재리뷰 clean.

3. **메타(아픈 것): 인덱스 후크를 *읽는* 것과 *적용*하는 것은 다르다.** 이번 Context 참고자산 줄엔
   062를 *안 적었고*(049·064만), 그래서 cap-the-raw-source를 상기하지 못한 채 cap-after-parse로
   재구현했다 — 내가 직접 쓴 learning의 결함을 다시 만들고 적대자가 잡아줬다. 교훈: 작업이 "외부
   응답 본문을 파싱·상한"을 건드리면 *그 키워드로* 인덱스를 한 번 더 긁어 관련 learning을 끌어와야
   한다. 회고는 *상기·적용*될 때만 복리고, 안 되면 같은 결함을 적대비용으로 다시 산다.

## 검증 사다리(메모리 verification-ladder, 비겹침)

- **단위(시맨틱)**: verify_062_http_error.mjs(node v24 TS erasure, 실 `Response` 스트림 경로) 10단언 —
  detail→메시지·없음/비-JSON/비문자열/공백뿐→폴백·길이600·제어문자strip·**원문(스택/토큰/payload)
  비노출**·**raw 바이트 상한(>64KB 절단→폴백)**·**안 끝나는 스트림→시간상한 폴백+reader cancel**.
  D2 `_dim_mismatch`는 직접 호출로 3요소+일치/probe미상 통과 확인.
- **라이브 통합(실 인프라)**: verify_062_live.py — 부팅 API에 머신토큰으로 중복이름 POST → 409 +
  `detail` 존재 + **안전 문자열 불변식**(Bearer/Traceback/토큰/경로 미포함) 실측. 차원불일치(L3)는
  비-1024 모델 후보 없어 SKIP(단위·브라우저가 가시화 입증).
- **브라우저(가장 충실)**: shot-collections-062-detail.mjs — 기존 컬렉션 이름 그대로 입력해 중복 유도
  (DB 무손상) → 토스트가 "→ 409"가 아니라 "같은 이름의 컬렉션이 이미 있습니다."를 보임. 스샷 캡처.
- **적대(타자, codex)**: 1차 = 핵심 불변식(detail-only·폴백·백엔드 안전문자열) 통과 + Medium(huge-body
  cap-after-parse)·Low(SSE hang) 적발 → 둘 다 수정. 2차(httpError 한정 재리뷰) = **Resolved/clean**
  (재사용 timeout=총경과 데드라인, 부분멀티바이트 decode 안전, 바이트복사 off-by-one 없음).

## 자산

- 스펙: docs/spec/062-admin-error-detail-surfacing.md
- 코드: admin/src/httpError.ts(신규 중앙 추출·bounded+timed reader), admin/src/api.ts(j·uploadDocument·
  streamChat 적용), packages/api/src/api/rag.py(_dim_mismatch 조치 추가)
- 검증: tests/verify_062_http_error.mjs, tests/verify_062_live.py,
  tests/browser/shot-collections-062-detail.mjs
- learning 065(큐레이션 메시지는 전송 경계가 버리면 무용지물 — 중앙 경계에서 surface)
