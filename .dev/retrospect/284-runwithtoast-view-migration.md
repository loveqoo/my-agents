# 284 — runWithToast 뷰 이관(스펙 309)

## 무엇을 했나
스펙 184 `runWithToast(fn, {success?,error?}) → Promise<boolean>`로 뷰마다 복붙된 mutation 토스트
관용구(`try{await mutate();message.success;<후속>}catch{message.error}finally{setBusy}`)를 단일화.
전수 인벤토리(11파일, 40 try/catch)를 FIT 11·FIT-CAUTION 19·SKIP 10으로 분류 → **27 이관·10 skip**.
공유 훅에 `errorPrefix` 1옵션 확장(사용자 승인). errorPrefix 순수 로직 4/4·diff 전수 리뷰·브라우저
왕복(9화면 무붕괴+Settings 성공토스트·결과소비·원복)으로 검증.

## 배운 것 / 복리 포인트

- **공유 헬퍼가 실사용보다 좁으면 사이트를 왜곡하지 말고 계약을 넓힌다**. 프리픽스 에러 6곳
  (`'수정 실패: '+e.message`)은 `opts.error ?? e.message`(프리픽스+detail 동시 불가)로 무손실 이관 불가.
  선택지는 (a) 프리픽스 버림=문맥 손실, (b) detail 버림=원인 손실, (c) 6곳 skip. 넷 다 사이트를 헐게
  한다. 근인은 **헬퍼 계약이 실제 호출 패턴('문맥: 상세')을 표현 못 함**이라 `errorPrefix?` 1옵션으로
  계약을 넓혀 6곳 무손실 흡수. N개 실 사이트가 헬퍼가 못 내는 모양을 원하면 사이트를 비틀지 말고
  경계를 넓혀라(단 공유 계약 변경이라 사용자 확인 선행). → [[structure-first-boundary-is-spec]]

- **"토스트 dedup"의 미묘한 핵심은 에러 규칙 3분(P/C/X)이다 — 뭉뚱그리면 조용히 UX 저하**. 원본
  `message.error(e instanceof Error ? e.message : 'STR')`(passthrough)를 `error:'STR'`로 옮기면 **e.message를
  고정 문자열이 덮어** 실제 실패 원인이 사라진다(happy-path 초록, 사용자만 나중에 "왜 실패했는지 안
  나오지" 발견). 올바른 이관: passthrough→**opts 없음**(헬퍼 기본이 이미 e.message-first)·custom-only
  (`message.error('STR')` e 무시)→`error:'STR'`·prefix→`errorPrefix`. "한국어 문자열을 error에 다 넣어"는
  passthrough 전부를 망친다 — 규칙을 사이트별로 판정. → [[prefer-positive-phrasing-in-copy]]

- **결과소비 vs UI정리 분리 — boolean 반환 헬퍼로도 "성공+결과" 시맨틱 보존**. runWithToast는 boolean만
  주고 await 결과를 버린다. 후속이 **결과값을 소비**하면(setUsers(updated)·setOrgName(r)·setSelectedId
  (created.id)) `fn` 화살표 **안**(await 뒤)에 둬 성공 시만·결과와 함께 실행. UI 정리(close/reset/reload)는
  `if(ok)`. 이 분리로 헬퍼가 결과를 반환하지 않아도 "성공에만·결과로" 시맨틱을 지킨다(결과파생 success
  문구도 fn 안 message.success로). → [[context-control-propagates-to-affordances]]

- **결과소비 부수효과가 토스트보다 강한 성공 증거다**. Settings 검증에서 transient 토스트 셀렉터는
  antd6 마크업 편차로 첫판 미포착이었으나, **입력 필드가 서버 echo("e2e-309-org")로 갱신**된 건 success
  경로(message.success 포함, setOrgName(r) 실행)가 돌았다는 durable 증거였다. 사라지는 UI(토스트)보다
  지속 상태(필드·목록·DB)를 겨누면 검증이 덜 깨지고 더 진실하다. → [[ui-verification-must-be-functional]]

- **정돈 작업은 "왜 하나"를 먼저 세워라 — 금칠과 핵심을 구분해 사용자에 올린다**. 실행 중 사용자가 "왜
  하는 거죠?"로 멈춰 세웠다. 정직한 답=이건 admin CRUD 일관성 다듬기(beauty=trust)지 플랫폼 핵심
  가치(저마찰 에이전트 생성·A2A)가 아니다=금칠에 가깝다. 비용(28곳·계약변경)·이득(일관성)·"핵심에서
  먼 다듬기"를 올리고 선택을 넘겼다("진행"). 보조 툴링 정돈을 핵심인 양 밀지 말고 트레이드오프를
  **선제**로 surface. → [[core-is-model-config-and-memory]] [[craft-first-then-compound-as-asset]]

## 검증 (사다리)
- **정적**: `tsc --noEmit` 0·`vite build` ✓(errorPrefix 확장 + 27 사이트).
- **훅 순수 로직**: errorPrefix 분기 4/4(node) — prefix→`{prefix}: {detail}`·custom→고정·passthrough→
  detail·prefix가 error보다 우선.
- **diff 전수 리뷰(적대 self-check)**: 27 사이트 P/C/X 규칙·결과소비 fn 내부·후속 if(ok)·가드/finally/
  프리컨디션 밖·deleteCurrent early-return 호이스트·approve/warning 조건 토스트 — 전부 계약 보존 확인.
- **기능(브라우저 왕복, tests/browser/verify-309-runwithtoast.mjs)**: 이관 9화면 렌더·정착·콘솔 치명0 +
  Settings save 안전 왕복(성공 토스트 발화 + 결과소비 필드=서버 echo + 원복). errorPrefix 실패 표면은
  브라우저 실패 주입이 취약해 순수 로직 체크로 대체(정직 기록).

## 남은 것 / 주의
- **SKIP 10**(스펙 OUT): 읽기 6(useAsyncData 후보)·결과분기 2결말 3(doUpload·trigger·testProvider)·
  409 특수분기 1(UsersView submit). runWithToast 계약("throw 안 하면 성공, 단일 토스트")과 근본 불일치.
- AgentsView·agents/*는 커스텀 플로팅 토스트(회고 166/167) — 영구 OUT.
- dev api(8000)·vite(5173) 기동 중(정상 dev 상태).
