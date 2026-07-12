# 317 — 코드 노드: 공통 노드 인터페이스 + 신뢰 레지스트리 (노드형 확장 2/3)

## 배경 / 동기

스펙 316이 등록 노드(설정 노드, kind=config)를 만들었다. 사용자 요구의 나머지 반쪽:
**UI로 설정하지 못하는 복잡한 로직은 코드로 노드를 작성해 등록**하고, 노드형에서 설정 노드와
똑같이 참조해 쓴다. 단, **플레이그라운드 오버라이드를 지원하기 위해 공통 노드 스펙(인터페이스)을
구현해야 한다**(사용자 요구 2026-07-13).

선례: 커스텀 에이전트(스펙 085)가 정확히 같은 문제를 에이전트 수준에서 풀었다 —
`CustomAgent` Protocol + 신뢰 레지스트리(`register_agent`) + 미적합 시 서빙 거부(089).
이 패턴을 **노드 수준으로 한 단계 내린다**.

## 합의된 결정 (2026-07-13, 스펙 316에서 승계)

- **동일 버전 덮어쓰기 허용** — 코드 노드의 버전은 코드(manifest)가 선언한다. 버전을 그대로 두고
  코드를 바꾸면 그 버전을 핀한 **모든 에이전트에 일괄 전파**(의도된 탈출구 — 핫픽스). 새 버전을
  선언하면 새 행이 발행되고 기존 핀은 옛 코드 경로를 유지한다.
- 네이밍: 화면은 "코드 노드"(등록 노드의 한 종류, kind=code Tag). "라이브러리" 미사용(316 결정 4).

## 설계

### 1) 공통 노드 인터페이스 (agent 패키지 — 085 미러)

```python
@dataclass(frozen=True)
class NodeManifest:
    name: str            # 카탈로그 식별 이름(스펙 148 규칙)
    version: int         # 이 코드가 구현하는 버전 — 같은 버전 재선언=덮어쓰기(합의 결정)
    description: str
    overridable: tuple[str, ...]  # 오버라이드 허용 표면 — _NODE_OVERRIDE_FIELDS의 부분집합만 유효

@runtime_checkable
class CustomNode(Protocol):
    def describe(self) -> NodeManifest: ...
    def build_step(self, node_cfg: dict, ctx: AgentBuildContext) -> NodeStep: ...
        # NodeStep = Callable[[state], Awaitable[dict]] — LangGraph 노드 함수(messages state).
```

- **신뢰 레지스트리** `register_node(cls)` + `_bootstrap_builtin_nodes()`(runtime의 register_agent와
  동일 구조 — dict에 등록된 우리 코드만, eval 없음, 085 §보안경계).
- `build_step`은 pipeline의 `_make_step`이 만드는 것과 같은 계약(메시지 in → `{"messages": [...]}`
  out). 도구가 필요하면 `ctx.tools`(이미 RBAC 스코프)에서 이름으로 고른다 — 노드가 에이전트
  권한을 넘을 수 없다(085 U2 승계). 레퍼런스 코드 노드 1개를 함께 출하해 인터페이스 과적합을
  둘째 구현 관점에서 측정(learning 039/085 — 단 첫 출하는 1개, 둘째는 실수요 때).

### 2) 카탈로그 동기화 (코드 → node_templates 행)

- 부팅 시 레지스트리의 각 코드 노드 manifest를 `node_templates`에 **upsert**(kind=code,
  config={"impl": 레지스트리 키} + manifest 메타). 같은 (name, version)이 이미 있으면 갱신
  (=동일 버전 덮어쓰기의 카탈로그 표현), 새 버전이면 새 행.
- config 노드와 이름공간을 공유(unique(name, version) 그대로) — 같은 이름에 config 버전과 code
  버전이 섞이는 것은 **금지**(kind 혼합 = 참조자가 성격을 예측 불가): upsert 시 이름의 기존 kind와
  다르면 부팅 경고 + 스킵(fail-safe, 조용한 변경 금지).
- 코드 노드 행은 API로 발행/삭제 불가(발행=코드 배포의 반영, 삭제=코드 제거의 반영) — 라우트가
  kind=code를 거부(409)하고 사유 안내. 삭제 가드(참조 409)는 동일 적용.

### 3) 실행 배선 (엔진 접합 — 최소 변경)

- 참조 해석(`resolve_node_refs`)은 무변경 — kind=code 행의 config(`{"impl": key}`)가 인라인으로
  치환되어 내려간다.
- pipeline `_make_step`이 노드에 `impl` 키가 있으면 노드 레지스트리에서 해석해 `build_step`으로
  스텝을 만든다(없으면 기존 설정 노드 경로 그대로). **미등록 impl = AgentConfigError**(조용한
  폴백 금지 — 089 패턴: 코드가 배포에서 빠졌는데 default로 만회하면 마스킹).
- normalize_nodes: `impl` 키 통과 화이트리스트 추가(prompt 필수 규칙은 code 노드에 미적용 —
  로직이 코드에 있으므로).

### 4) 오버라이드 (공통 인터페이스의 존재 이유)

- 세션 오버라이드는 manifest의 `overridable` 표면에 든 필드만 병합(그 외는 무시 + 트레이스에
  mismatch 계열로 표면화 — 스펙 287 일관). 예: overridable=("model",)이면 모델만 갈아끼워 테스트.
- UI(오버라이드 패널·폼 미리보기)는 코드 노드에 대해 선언된 표면만 편집 가능으로 렌더하고
  나머지는 "코드가 소유" 읽기 전용 표기.

### 5) UI

- 등록 노드 목록/상세: kind Tag("설정"|"코드"), 코드 노드는 발행/삭제 버튼 대신 "코드로
  관리됩니다" 안내 + manifest 설명·overridable 표면 표시.
- 에이전트 폼 참조 픽커: 코드 노드도 동일하게 선택(구분 Tag만).

## 범위 밖 (OUT)

- ③ 노드에서 에이전트 호출(스펙 318).
- 코드 노드의 런타임 업로드/핫 리로드(코드는 레포+배포로만 — eval/동적 import 없음, 085 경계).
- agent-flow 스킬의 코드 노드 코드젠 확장(수요 확인 후 후속 — 첫 코드 노드는 손으로).
- per-노드 오버라이드 표면의 세밀 검증 UI(선언 표면 렌더까지만).

## 검증 (사다리 3런)

- **단위(결정적)**: `tests/verify_317_code_node.py` — ① 레지스트리 등록/미등록 impl=AgentConfigError
  (마스킹 0), ② 부팅 upsert: 신규 발행·동일 버전 덮어쓰기·kind 혼합 스킵+경고, ③ 코드 노드 참조
  에이전트 실행(mock step이 메시지에 표식 append → 최종 답에 표식), ④ 오버라이드: overridable 안
  필드만 병합·밖 필드 무시 표면화, ⑤ API 발행/삭제의 kind=code 거부.
- **실 인프라**: 레퍼런스 코드 노드를 참조한 노드형 채팅 왕복 — trace.graph에 노드명·동작 효과.
- **적대(codex)**: 여집합 — impl 키로 레지스트리 밖 코드 도달 경로, 오버라이드로 선언 표면 우회,
  upsert가 config 노드를 덮는 경로, 참조 해석과 kind 게이트의 비대칭.

## codex 적대 검증 → 수정 (P0 0 · P1 3 수정 · P2 2 수정)

- **P1 eval 입구 누락**: `_build_eval_graph`가 `impl_config`를 주입하지 않아 노드형/산출물형 평가가
  기본 단일 노드로 **조용히 퇴화**(실제 서빙과 다른 것을 채점), 미등록 코드 노드도 설정 오류 대신
  폴백 실행. → eval에도 `impl_config` 주입(네 번째 입구) + 그래프 조립 AgentConfigError를 error obs로
  접기(verify H6). 채팅·A2A·재개에 이은 **입구 열거의 빠진 칸** — [[async-completion-needs-reader-contract]] 류의 "모든 입구 정합".
- **P1 승인 재개 500 누출**: `_rebuild_resume_graph`가 AgentConfigError를 잡아 None 반환하는데 호출부가
  None 가드 없이 tuple unpack → `TypeError`. → 반환형 `| None` + 호출부 None 가드(graceful 재개 불가).
- **P1 sync 고아 정리 TOCTOU**: 부팅 동기화의 stale scan→delete가 에이전트 저장(ref 검증)의 advisory
  lock과 직렬화 안 됨 → dangling ref. → sync가 manifest·기존 code 행 이름을 정렬 순 선잠금(발행·삭제·
  저장과 같은 키 공유).
- **P2 sync↔config 발행 kind 혼합**: 같은 lock 미공유라 fail-safe가 경합 예외 의존. → 위 선잠금으로
  결정적 직렬화(unique는 최후 방어).
- **P2 오버라이드 패널 코드 노드 크래시**: collapsed 헤더가 `n.prompt.trim()` 무조건 호출 → code
  노드(prompt 없음) `undefined.trim()`. → UI에서 코드 노드 분기(읽기 전용 안내)로 prompt 접근 차단,
  브라우저 프로브로 JS 에러 0 확인.
- **확인된 방어(비발견)**: 인라인 `{impl}` 저장 우회 막힘(_normalize_node가 ref 아니면 prompt 필수·
  impl 드롭), 세션 오버라이드 화이트리스트에 impl 없음. 코드 노드의 임의 부수효과는 신뢰 레지스트리
  전제와 일치(사용자 업로드·동적 실행 경로 없음).

## 완료 조건

- 코드 노드 1개(레퍼런스)가 등록→참조→실행 왕복으로 동작하고, 동일 버전 코드 변경이 핀 에이전트에
  전파(측정), 새 버전 선언은 새 행(기존 핀 무영향).
- 미등록 impl은 명확한 설정 오류(폴백 마스킹 0), 오버라이드는 선언 표면만.
- ruff/mypy/tsc/vite 클린, verify_316·파이프라인 회귀 무회귀.
