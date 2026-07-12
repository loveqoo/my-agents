# 309 — runWithToast 뷰 이관(mutation 토스트 관용구 정본화)

## 배경
스펙 308이 useAsyncData 이관을 마치며 **runWithToast(~26 사이트)**를 후속으로 남겼다(backlog:329).
`runWithToast(fn, {success?, error?}) → Promise<boolean>`(스펙 184, `admin/src/hooks.ts`)로 뷰마다
복붙되던 mutation 토스트 관용구
`try { await mutate(); message.success(...); <후속> } catch(e) { message.error(...) } finally { setBusy(false) }`
를 단일화한다. 전수 인벤토리(11 파일, AgentsView·agents/*는 커스텀 플로팅 토스트라 OUT)로 40 try/catch
사이트를 **FIT 11·FIT-CAUTION 19·SKIP 10**으로 분류했다.

## 훅 계약 확장 — errorPrefix (사용자 승인)
프리픽스 에러 6곳(`'수정 실패: ' + e.message`)은 현 계약(`opts.error ?? e.message` — 프리픽스+detail
동시 불가)으로 무손실 이관 불가. **공유 훅이 실사용보다 좁은 것**이 근인이므로 계약을 실사용에 맞춰
1옵션 확장(structure-first):

```ts
// runWithToast opts에 errorPrefix?: string 추가
message.error(
  opts?.errorPrefix ? `${opts.errorPrefix}: ${e.message}`
                    : (opts?.error ?? e.message),
)
```

이로써 `errorPrefix: '수정 실패'` → `수정 실패: <detail>` 원문 그대로. 6곳(AgentMemoryPanel add·
EvalView save·start·PagedMemoryList saveEdit·remove·SessionsView doEnd)이 재사용.

## 이관 대상 (IN — FIT 11 + 이관 가능 FIT-CAUTION)
분류·라인은 인벤토리 확정. 변환 규칙별로:

- **FIT(깨끗) 11**: BlocksView `runRediscover`·`togglePublish` / CollectionsView `EditModal.save`·
  `doDeleteDoc`·`submitCreate`·`doDelete` / ProviderModelView `deleteProviderRow`·`createModelRow`·
  `deleteModelRow` / UsersView `onRevokePolicy`·`onGrantPolicy`. `const ok = await runWithToast(() =>
  mutate(), {success?, error})`; 성공 후속(reload/close/reset)은 `if (ok) { ... }`.
- **조건부 double mutation**: BlocksView `upsertMcp`·`deleteCurrent`·`savePersona`·`saveBlock` /
  EvalView `save` / ProviderModelView `submitProvider`. 두 분기(create/update, mcp/block)를 `fn` 화살표
  안에 그대로(다중 await OK). `deleteCurrent`의 **try 내부 early-return**(resource 없으면)은 runWithToast
  호출 전으로 **가드 호이스트**.
- **결과값 소비 후속**: BatchView `save`(applyCfg(result)) / SettingsView `save`(setOrgName(r)) /
  ProviderModelView `submitProvider`(created.id)·`makeDefault`(updated) / SessionsView `doEnd`(setDetail
  (updated)) / UsersView `toggleActive`·`onGrant`·`onRevoke`(setUsers(updated)) / BlocksView
  `applySelected`. → **결과 소비 상태갱신은 `fn` 안**(await 후, throw 시 미실행), UI 정리(close/reset)는
  `if (ok)`.
- **결과 파생 success 문구**: BlocksView `applySelected`(`${applied}개 반영`) / BatchView `save` /
  ProviderModelView `makeDefault`(`기본 → ${updated.name}`). → opts.success 대신 **`fn` 안에서 mutation
  직후 `message.success(...)`**(성공 경로만). 상태 파생(EvalView `start`의 `runModels.length>1`)은 호출
  전 **문자열 precompute** 후 opts.success로.
- **프리픽스 에러**: 위 errorPrefix 6곳 → `errorPrefix: '수정 실패'` 등.
- **approve/warning 분기**: ApprovalsView `resolve` — 성공 후 decision별 `message.success`(승인)/
  `message.warning`(거부)는 `if (ok) { ... }`에서 조건 토스트(opts.success 미지정).

## 원칙(계약 보존)
- **버튼 로딩은 호출자 소유** — `finally { setBusy(false) }`는 runWithToast 밖에 그대로 유지(훅은 토스트만).
- **호출 전 프리컨디션 가드**(name/JSON 검증·`if(!x) return`)는 runWithToast 밖에 그대로.
- 성공에만 걸리던 후속은 `if (ok)`로, 성공/실패 무관 정리는 그대로. **부정문("실패 시 X 안 함")이 아니라
  "성공 시 X"로 표현**(긍정 프레이징).
- SKIP 사이트는 **손대지 않음**(부분 이관이 더 위험).

## OUT (SKIP 10 — 사유)
- **읽기(mutation 아님)**: BatchView `loadRuns`·`load` / ProviderModelView `loadRegModels`(silent catch) /
  CollectionsView `runHealth` / UsersView `load` / BlocksView `runDiscover`(list-only, UI 상태만). 성공
  토스트 없음·결과를 state로 — useAsyncData 후보이지 runWithToast 아님.
- **결과 분기 2결말**(mutation 성공했으나 result가 성공/경고/에러를 가름): CollectionsView `doUpload`
  (`doc.status==='error'`) / BatchView `trigger`(res.summary 다분기) / ProviderModelView `testProvider`
  (`r.ok`). runWithToast는 "throw 안 하면 성공"이라 근본 불일치.
- **catch 특수 분기**: UsersView `submit`(409 감지 → '이미 존재하는 이메일'). 에러 내용 조건 분기라
  단일 문자열/프리픽스로 표현 불가.
- **runWithToast 미채택 파일**: AgentsView·agents/*(커스텀 플로팅 토스트, 회고 166/167 선례) — 스캔 제외.
- **EvalView promise-chain**(try/catch 아님): `suggestEvalCases().then().catch()` 등 4곳 — 타깃 형태 아님, 보류.

## 검증
- **정적**: `tsc --noEmit` 0·`vite build` ✓(errorPrefix 확장 + ~28 사이트 후 무붕괴).
- **훅 단위**: errorPrefix 분기 동작(prefix 있으면 `${prefix}: ${msg}`, 없으면 기존) — 소형 대조.
- **기능(브라우저 왕복)**: 대표 mutation을 실제 수행해 **토스트 + 효과 + 실패 토스트**를 단언(외형 아닌
  동작, learning UI 검증). 커버: 생성/삭제(Collections·Provider·Users 권한)·토글(Users toggleActive·
  Blocks publish)·결과소비(Sessions doEnd·Provider makeDefault)·errorPrefix 에러 표면. 성공 boolean →
  후속(close/reload) 발화까지.
- **적대**: 순수 프론트(백엔드 무변경). runWithToast가 **성공 후속을 `if(ok)`로 옮기며 실패 시 후속이
  더는 안 도는지**(원본은 catch로 건너뜀 = 동치), **결과소비 상태갱신이 throw 시 미실행인지**(fn 안
  await 뒤라 보장) diff 전후 대조 self-check. errorPrefix가 **success 경로엔 안 새는지**(catch 전용) 확인.
