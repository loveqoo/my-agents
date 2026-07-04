# 153 — RAG 생성 폼: 임베딩 상위 + 기본 프리셀렉트 (스펙 175)

구남님: "임베딩은 한 번 정하면 못 바꾼다. 등록 시 모델 설정이 상위로 올라가야. 기본 모델이 선택돼 있어야."

## 한 것
CreateModal을 "불변 결정 3인방(이름→종류→임베딩)"을 위로, 편집 가능(별명·설명)을 아래로 재배치.
임베딩 라벨에 빨강 "(생성 후 변경 불가)". `useEffect`에서 `models.find(m=>m.is_default)` 프리셀렉트
(없으면 단일 모델 fallback). 옵션 라벨에 "· 기본" 표기. 프론트만·페이로드 무변경.

## 배운 것
- **폼 순서가 되돌림 가능성을 반영해야 한다.** 가장 비가역인 결정(임베딩=차원 고정)이 가장 아래 숨어
  있었다. UX 원칙: *못 바꾸는 것부터 위로, 언제든 바꾸는 것은 아래로.* 실수 비용이 큰 필드일수록 시선
  경로 상단 + 불변임을 명시.
- **기본값은 서버에 이미 있으면 프리셀렉트로 실수를 줄인다.** `Model.is_default`(kind별 기본)가 API에
  이미 노출돼 있었는데 생성 폼은 "모델이 하나일 때만" 채웠다 — 여럿이면 빈칸. 기본을 우선 채우니 흔한
  경로가 0클릭. [[not-missing-just-unexposed]]의 연장(기능이 아니라 활용이 빠짐).
- **antd 6 모달 콘텐츠 클래스는 `.ant-modal`**(`.ant-modal-content` 아님) — 테스트 셀렉터 갱신.
  또 "값 채워짐"은 selection-item DOM보다 **innerText에 마커("· 기본") 포함**으로 검사가 견고(CSS
  말줄임에도 innerText는 full). [[verify-ui-in-browser-proactively]] 실측이 셀렉터 오류를 잡음.

## 검증
tsc clean·브라우저 e2e 5/5(임베딩>별명·임베딩>설명·이름<종류<임베딩·불변힌트·"· 기본" 프리셀렉트).
스크린샷 육안(순서·빨강 불변 힌트·기본 모델 프리셀렉트 확인). 기본이 실제 mlx 모델(is_default 경로 실증,
단일-모델 fallback 아님).

## OUT
- 임베딩 사후 변경(불변이 의도 — 재임베딩 별도 축). 기본 지정 UI는 프로바이더·모델 뷰에 이미 있음.

[form-order-reflects-reversibility,prefill-server-default-cuts-mistakes,antd6-modal-class,innertext-marker-over-dom-selector]
