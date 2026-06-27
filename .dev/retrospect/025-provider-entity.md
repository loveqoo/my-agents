# 025 — Provider 엔티티: 인라인 필드를 1급 관계로 정규화하며 배운 것

스펙: `docs/spec/archive/035-provider-entity.md` (P1, 로드맵 033 의존순 두 번째 단계)
대상: `ModelConfig`의 인라인 연결처(`provider`/`base_url`/`api_key`)를 1급 `Provider`
테이블로 분리. 모델은 `provider_id` FK(ondelete RESTRICT)로 참조 → "provider 1회 등록 →
하위 모델이 base_url·키 상속". 어드민 프로바이더 탭 + 기존 모델행 마이그레이션.

## 무엇을 했나
- 백엔드: `Provider` 엔티티 + CRUD 라우터(암호화/마스킹/마스킹수정=보존·""=제거),
  `ModelConfig` 인라인필드 제거·`provider_id` FK, 모든 모델 조회에 `selectinload(provider)`.
- 마이그레이션: 기존 모델을 base_url별로 묶어 provider 생성·backfill·NOT NULL·FK·인라인컬럼 드롭(가역).
- 프론트: `api.ts` Provider 타입+CRUD·Model 셰이프 변경, `ProvidersView`(신규), `ModelsView`
  base_url/키 입력 → 프로바이더 드롭다운, AdminShell 탭 등록.
- 검증: 불변식 인프로세스 ASGI 테스트(20단언, 자가정리) + tsc/vite + 브라우저 스샷 4뷰 +
  타자 2인(독립 서브에이전트 + codex) 모두 SHIP 수렴.

## 교훈 1 — 회고가 복리로 작동했다: "마지막 소비처 함정"을 *테스트 전에* 잡았다
retrospect 023·024가 두 번 연속 경고한 그 함정이 이번에도 잠복했다. `chat.py _load_context`만
고치고 끝낼 뻔했으나, 이번엔 **고치자마자 작업키워드(`base_url`/`api_key`/`select(ModelConfig)`)로
전수 grep**했고 두 번째 모델로딩 경로(`_build_mem_cfg`/`_default_chat_model`/`resolve_agent_mem_cfg`,
스펙 029 메모리 CRUD가 쓰는)가 여전히 옛 셰이프를 읽고 있었다. 024는 tsc가 *사후*에 잡아줬지만(TS),
이번 파이썬 백엔드엔 그 안전망이 없어 **런타임까지 갔으면 폭발**할 자리였다.
→ **적용점**: 회고는 "다음 작업 Context에서 상기·적용될 때만 복리"라는 [[dont-skip-context-recall-learnings]]가
실증됐다. 셰이프 변경 직후 grep 전수검사를 *습관*으로 박으면, 타입체커 없는 언어에서도 024의 교훈이 산다.

## 교훈 2 — 인라인→관계 정규화의 숨은 비용은 N개 소비처의 eager-load 의무
인라인 컬럼을 관계로 빼면, `m.provider.base_url`을 읽는 *모든* 경로가 세션 종료 전에
`selectinload(provider)`를 걸어야 한다. 안 그러면 직렬화 시점(세션 detach 후) lazy-load가 터진다.
즉 **교훈 1의 "모든 소비처 grep"이 곧 selectinload 감사와 같은 작업**이다 — 한 번의 전수검사가
두 위험(옛 셰이프 잔존 + lazy-load 누락)을 동시에 막는다. 두 리뷰어 모두 이 지점을 최우선 점검했다.
→ **적용점**: ORM에서 필드를 관계로 승격할 땐 "소비처 전수 grep → 각 경로 eager-load 확인"을
한 체크리스트로 묶는다. 직렬화 함수(`model_to_out`)에 "이 관계는 eager-load 전제" 주석을 남긴다.

## 교훈 3 — 승인된 손실 결정도 "조용히" 두지 말고 가시화한다
codex가 유일하게 짚은 것: base_url 그룹핑은 **같은 엔드포인트에 서로 다른 자격증명**이 섞이면
첫 키만 남기고 버린다(스펙 035 승인 결정). SHIP을 막진 않지만, 나는 승인된 *동작은 유지*하되
마이그레이션에 **복호화-평문 비교로 진짜 충돌일 때만 경고 로그**를 넣었다(Fernet 비결정이라 암호문
비교는 거짓양성). 이건 "no silent caps — 버린 건 log로 드러내라"([[numeric-verification-unlocks-autonomy]]
인접 원칙)의 적용이다. 이미 적용된 DB엔 재실행 안 되지만, 사용자가 다른 브랜치·머신에서 fresh로
돌릴 때 살아난다.
→ **적용점**: 리뷰어가 "lossy하지만 의도된 동작"을 지적하면, 결정을 뒤집기 전에 **손실을 관측가능하게**
만드는 저비용 수단(경고 로그·메트릭)부터 검토한다. 결정 존중 + 가시성 확보가 둘 다 된다.

## 교훈 4 — 기존 스샷 하베스트 패턴 재사용 = 거의 공짜 화면검증
`shot-sessions-034.mjs`의 로그인→탭이동→단언 골격을 복제해 `shot-providers-035.mjs`를 만들었다.
헤더 텍스트(`프로바이더` 컬럼 존재·`키` 컬럼 부재)·마스킹(`•`) 노출·암호문(`gAAAAA`) 비노출을
프로그램적으로 단언하니, 스샷이 단순 "눈으로 봐주세요"가 아니라 **수치 검증**이 됐다.
→ **적용점**: 화면검증도 가능한 한 텍스트/DOM 단언으로 자동화한다([[verify-ui-in-browser-proactively]]의
강화판). 뷰가 추가될 때마다 직전 shot 스크립트를 복제하면 한계비용이 거의 0.
