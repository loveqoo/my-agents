# 418 — 능력 설정 편집이 전체 새로고침 유발 수정(제자리 갱신)

> 상태: **완료**(tsc0·브라우저 SHOT418_OK) · 2026-07-20 · 발단: 개발자 "프로바이더 모델의 능력설정에서
> 하나만 설정해도 새로고침이 됩니다."

## 진단
`CapsEditor.save()`(ProviderModelView.tsx:239)가 능력·파라미터 토글마다 PUT `updateModel` 후
`onSaved()` = `refresh()` = **`reloadProviders()` + `reloadAvail()`**(551행)를 호출한다. 즉 능력 하나
토글에 **프로바이더 목록 + 사용가능 모델 목록 전체를 재조회** → useAsyncData가 loading→data undefined로
뒤집혀 뷰 전체가 리마운트(팝오버 닫힘·깜빡임 = "새로고침").

과잉인 이유: 능력·파라미터 편집은 그 Model의 `capabilities`/`params`만 바꾼다. 프로바이더 목록·
사용가능 목록의 registered/registered_id/kind/기본은 **불변**. 전체 재조회가 불필요했다.

## 설계 — PUT 응답으로 그 모델만 제자리 갱신(learning 084 in-place-update)
`regModels`는 `useAsyncData`가 아니라 일반 `useState<Model[]>`(510행, `setRegModels(await listModels())`
로 로드)라 제자리 패치가 가능하다.
- `CapsEditor.save()`가 `updateModel` 반환(갱신된 Model)을 `onSaved(updated)`로 넘긴다
  (`onSaved: (updated: Model) => void`).
- 부모(870행)는 `onSaved={(updated) => setRegModels(prev => prev.map(m => m.id === updated.id ? updated
  : m))}` — 그 모델만 교체. **재조회 0·loading 미발생 → 리마운트 없음 → 팝오버 유지.** 재열람 시에도
  regModels가 최신이라 정확(store-the-source, learning 084).
- 레이스 없음: `busy`가 저장 중 컨트롤을 비활성 → 순차 저장(응답 기반 패치라 stale 도착물 문제 부재).

## 검증(ui-verification-must-be-functional) — 달성(tests/browser/shot-418, 네트워크 단언)
- [x] 능력 토글 → **PUT /models 1회·프로바이더 GET 0·avail GET 0**·팝오버 **유지**(SHOT418_OK).
- [x] 재열람 → 저장값 정확(true→false 반영, 재열람 false==false — 제자리 갱신 실측).
- [x] 등록/해제/기본전환 등 기존 refresh 경로 무변경(목록 자체 변경이라 reload 유지) — onSaved만 교체.
- [x] tsc 0.

## OUT
- 낙관적 즉시 반영(토글 순간 값 갱신 + 롤백, learning 056) — 응답 기반으로도 새로고침이 사라지므로
  과투자 회피. busy 짧은 비활성은 수용(별건 폴리시면 후속).
