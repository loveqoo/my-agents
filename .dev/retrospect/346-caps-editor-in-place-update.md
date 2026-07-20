# 346 — 능력 설정 편집이 전체 새로고침 유발(스펙 418)

## 발단
구남님: "프로바이더 모델의 능력설정에서 하나만 설정해도 새로고침이 됩니다."

## 진단
`CapsEditor.save()`가 능력·파라미터 토글마다 PUT `updateModel` 후 `onSaved()` = `refresh()` =
`reloadProviders()` + `reloadAvail()`(전체 목록 2개 재조회)를 불렀다. `useAsyncData`의 `reload()`는
loading→data undefined로 뒤집으므로 뷰 전체가 **리마운트** → 팝오버가 닫히고 깜빡임 = "새로고침".

## 배운 것

### 1. 편집이 바꾸는 범위 = 갱신해야 할 범위. 전체 재조회는 게으른 과잉
능력·파라미터 편집은 **그 Model 하나**의 capabilities/params만 바꾼다. 프로바이더 목록·사용가능
목록의 registered/kind/기본은 불변. 그런데 편집 성공 후 관성적으로 `refresh()`(전체)를 불렀다.
"저장했으니 다시 불러오자"는 반사가 **바꾼 것보다 훨씬 넓게** 재조회하게 만든다. 갱신 범위를 편집
범위에 맞춰야 한다([[learning 084 in-place-update]]) — PUT 응답으로 그 행만 제자리 교체.

### 2. `useAsyncData`의 reload는 리마운트를 부른다 — 제자리 패치엔 부적합
`reload()`는 `nonce++`로 재fetch → `loading=true`·`data=undefined` 순간이 생겨 소비 컴포넌트가
언마운트된다(팝오버·스크롤·포커스 소실). 반면 편집 대상이 **일반 `useState`**(regModels)면
`setState(prev => patch)`로 loading 없이 그 항목만 갱신 → 리마운트 없음. 상태 출처가 useAsyncData면
reload밖에 없어 이 문제를 물려받으므로, in-place 갱신이 필요한 목록은 일반 useState가 유리(또는
useAsyncData에 setData 노출 — 이번엔 이미 useState라 불요).

### 3. 응답 기반 패치면 낙관+토큰 없이도 레이스가 없다
[[learning 056 optimistic-update]]는 stale 도착물이 최신을 덮는 레이스를 경고하지만, 이번은 **낙관이
아니라 PUT 응답을 받은 뒤** 그 응답으로 패치한다. `busy`가 저장 중 컨트롤을 비활성화해 순차 저장을
강제하므로 동시 요청 자체가 없다. 새로고침 제거가 목표면 낙관+staleness-token은 과투자 — 응답 기반
in-place가 더 단순하고 충분(YAGNI).

### 4. 네트워크 단언이 "새로고침 없음"의 정직한 증거
"팝오버가 유지되나"만 보면 우연히 초록일 수 있다. **토글 후 GET 재조회 수 = 0, PUT = 1**을 실제
네트워크로 세는 게 [[ui-verification-must-be-functional]]의 증거 — 스샷보다 강하다. antd v6 팝오버
내부 클래스가 `.ant-popover-container`(구 `.ant-popover-inner` 아님)라 셀렉터도 실측으로 확인.

## 자산화 후보(관련)
[[learning 084 in-place-update]] [[transient-request-race]] [[whole-fix-over-minimal-patch]]
[[ui-verification-must-be-functional]] [[verify-ui-in-browser-proactively]]
