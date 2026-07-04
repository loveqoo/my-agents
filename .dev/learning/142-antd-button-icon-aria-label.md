# 142 — antd 아이콘 버튼은 접근성 이름에 아이콘 라벨이 앞에 붙는다

## 증상
Playwright에서 `page.getByRole('button', { name: '편집', exact: true })`가 **0건 매치**로 깨진다.
버튼에 텍스트 "편집"이 분명히 있는데도.

## 원인
antd `<Button icon={<EditOutlined/>}>편집</Button>`은 아이콘 `<span role="img" aria-label="edit">`을
렌더한다. 버튼의 **접근성 이름(accessible name)은 아이콘 aria-label + 텍스트를 이어붙인 `"edit 편집"`**이
된다. `exact: true`는 정확히 "편집"을 요구하므로 불일치.

## 처방
- 아이콘 있는 antd 버튼은 **`exact: true` 금지** — 정규식 부분일치를 써라: `getByRole('button', { name: /편집/ })`.
- 또는 텍스트로: `page.getByText('편집', { exact: true })`(단 버튼 외 요소와 충돌 주의).
- 접근성 이름 확인: `await btn.evaluate(el => el.getAttribute('aria-label') || el.textContent)`.

## 파급
`tests/browser/*.mjs`에서 아이콘 버튼을 `exact:true`로 잡는 곳은 전부 같은 함정. 새 브라우저 스크립트
작성 시 아이콘 버튼은 처음부터 정규식 부분일치로. (스펙 168 오버레이 감사에서 persona-edit '편집'·
collection-create 버튼 매칭이 이걸로 깨졌다 발견.)

## 관련
반응형 함정 형제: 모바일(<992px)에서 DataTable이 `<table>`이 아니라 카드(div)로 렌더(스펙 145) →
`table tbody tr` 셀렉터가 모바일서 0건. 행 클릭은 뷰포트별 셀렉터 분기 필요.

[playwright,antd,accessible-name,icon-button,responsive-selector-trap]
