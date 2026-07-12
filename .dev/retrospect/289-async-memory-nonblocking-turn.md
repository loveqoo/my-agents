# 289 — 자동 기억 저장 비차단화 + 완료 트레일링 이벤트 (스펙 314)

## 무엇을 했나
"인스펙터가 너무 오래 걸린다"는 보고를 닫았다. **측정으로 진단한 결과 인스펙터가 아니라 자동 기억
저장(memory.add)이 `done`을 막던 것**이었다. memory.add를 `done` 뒤 백그라운드로 빼고, 완료되면
트레일링 `event: memory`로 인스펙터에 조용히 반영한다.

- **백엔드**: `_final_frames` 재정렬(답변→trace→done 먼저·저장은 백그라운드 detached+shield 태스크)·
  `memory.add`가 저장 요약 반환(백엔드 3종)·`_bg_memory_add`/`_finalize_memory_trace`(영속 병합).
- **프론트**: `[DONE]`에서 리더를 안 멈추고 계속 읽어 트레일링 `event: memory` 수신(api.ts)·`onMemory`가
  mid로 그 턴을 **조용히** 패치(딴 화면=no-op)·인스펙터 "자동 저장된 기억" 섹션(pending=Spin+Tooltip,
  완료=결과)·채팅 인스펙터 링크에 로딩 스피너.

## 배운 것 / 복리 포인트

- **"X가 느리다"의 X가 진짜 병목인지부터 측정하라 — 여기선 인스펙터가 아니라 memory.add였다**.
  "인스펙터가 느리다"에 곧장 인스펙터(trace 조립/렌더)를 뜯었으면 헛수고였다. 프레임 도착 시각을
  실측하니 trace는 0ms·1.2KB(무죄), 유일한 동기 지연은 장기 메모리 저장(mem0 LLM 추출)이 `done`
  앞을 막던 것. 사용자 답("답변 후 처리 중 지속")이 post-stream 지연을 가리켰고, 측정이 그걸 memory.add로
  못박았다. **증상이 지목하는 컴포넌트와 원인 컴포넌트는 다를 수 있다.** → [[probe-deeper-before-concluding]]

- **스트리밍 타이밍은 측정 도구가 가릴 수 있다 — ASGITransport 버퍼 vs body_iterator**. httpx
  ASGITransport로 SSE를 읽으면 프레임이 버퍼링돼 done·memory가 같은 시각(0ms)으로 뭉쳐 보였다(거짓
  실패). `StreamingResponse.body_iterator`를 직접 순회해 **서버 yield 지점**을 타임스탬프하니 done=36ms·
  memory=1564ms로 갈라져 재정렬이 증명됐다. **측정이 기대와 어긋나면 대상 코드 전에 측정 경로(버퍼링)를
  의심하라.** → [[probe-deeper-before-concluding]] [[verification-ladder-three-rungs]]

- **detached 태스크는 "취소 지점 앞"에서 만들어야 한다 — codex P0**. 처음엔 저장 태스크를 `yield done`
  **뒤**에 만들었다. 그런데 클라이언트가 done 직후 끊으면 async generator가 yield 이후로 재개되지 않아
  **태스크 자체가 안 생겨** 저장이 유실됐다(shield·강참조가 지킬 대상이 없음). "끊겨도 저장 보장"이라던
  내 주장이 P0로 부서졌다. 수정=태스크를 `yield done` **앞**에서 생성·등록. **fire-and-forget의 안전은
  '무엇을 shield하나'가 아니라 '언제 생성하나'가 먼저다 — 취소가 닿는 yield보다 앞서 만들어야.**
  내 verify는 body_iterator를 끝까지 순회해 이 취소 경로를 못 봤다(자가검증 사각). → [[installed-guard-isnt-covering-guard]] [[adversarial-review-before-destructive-ship]] [[use-codex-for-adversarial-verification]]

- **상태 표식(pending)은 "완료를 보장하는 채널"에만 실어라 — 영속하면 stuck**. memoryPending을 영속
  trace에 넣으니, 저장을 완료 못 하면(서버 재시작·hang) 새로고침 스피너가 영영 돌 위험(codex P1). 수정=
  **pending은 라이브 스트림에만**(영속엔 memorySaved 최종만), + 저장 자체에 타임아웃(hang이어도 pending
  해제). + mid 없으면(persistHistory=false) 애초에 pending 표식 안 함(해제 이벤트가 mid 기반이라).
  **낙관 표식은 그걸 반드시 지우는 경로가 보장될 때만 남겨라.** → [[complement-attack-can-be-honest-boundary]]

- **비동기 완료를 프론트에 알리려면 리더 계약(멈춤 조건)부터 바꿔야**. 트레일링 이벤트는 done 뒤에
  오는데, 프론트 리더가 `[DONE]`에서 `return`하면 그 이벤트를 못 받는다. `[DONE]`을 "턴 논리 완료
  (onDone)"로만 처리하고 **리더는 스트림이 닫힐 때까지 계속 읽게** 바꿨다. 스피너 해제는 promise
  resolve가 아니라 onTrace/onDone로 이미 하므로 지연 재발 없음. 대신 새 메시지로 controller가 교체되면
  옛 스트림 finally가 전역 상태를 안 건드리게 `=== controller` 가드. **채널을 열어두면 그걸 소비하는
  쪽의 종료 조건·자원 정리를 같은 변경에서 정렬해야.** → [[context-control-propagates-to-affordances]]

## 검증 (사다리 3단)
- **실측**: `tests/verify_314_async_memory.py` VERIFY314_OK — memory.add를 슬립+가짜반환으로 몽키패치,
  body_iterator 직접 순회로 last_text→done=15ms·done→memory=1536ms(저장이 done 뒤임을 실측)·memorySaved·
  올바른 mid·영속 병합·**⑥ P0 회귀**(done 직후 aclose로 이탈해도 저장·영속 완료).
- **프론트 기능 왕복**: `tests/browser/verify-314-async-memory-ui.mjs` VERIFY314_UI_OK — 장기 메모리
  에이전트로 전송→인스펙터 "자동 저장된 기억" 섹션→**리로드 없이** pending 해제(트레일링 이벤트 수신
  증명)·치명 에러 0. 무회귀: verify-node-timeline-192 15/15(비메모리 인스펙터·스트리밍 정상).
- **적대(codex)**: P0 1·P1 3·P2 2 발견 → 전부 수정 또는 경계 문서화. ruff/mypy/tsc/vite 클린.

## 남은 것 / 주의
- **OUT**: 폴링 방식(미채택 — 스트림+영속으로 대체) · 배포용 인스펙터 제거 옵션(trace 이미 경량·A2A
  서빙은 trace 없음 → `chat()` 직접 노출 시에만) · 무중단 인제스트 · mem0 호출 자체 취소 가능화(hang
  시 스레드 고아).
- **경계**: persist~finalize 사이 크래시=그 턴 memorySaved 소실(단일 워커, pending 미영속이라 스피너
  잔존은 없음). mem0 hang 시 스레드 고아(바운드·드묾).
- dev api(8000)·vite(5173) 기동 중.
