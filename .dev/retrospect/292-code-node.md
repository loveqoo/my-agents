# 292 — 코드 노드: 공통 노드 인터페이스 + 신뢰 레지스트리 (스펙 317)

## 무엇을 했나
노드형 확장 3부작 2탄. UI로 설정 못 하는 복잡 로직을 **코드로 노드화**(kind=code)해 등록 노드처럼
버전 핀 참조한다. 커스텀 에이전트(스펙 085 `CustomAgent`+`register_agent`) 패턴을 노드 수준으로 내림:
`CustomNode` Protocol(describe/build_step) + 신뢰 레지스트리 + 부팅 시 manifest→node_templates upsert.
레퍼런스 코드 노드 `mask-pii`(이메일·전화 정규식 마스킹 — 프롬프트로는 못 보장하는 결정적 후처리).
오버라이드는 manifest가 선언한 표면만(공통 인터페이스를 요구한 이유). 미등록 impl은 어느 입구에서도
설정 오류(폴백 마스킹 0).

## 배운 것 / 복리 포인트

- **"impl_config를 주입하는 입구"는 닫힌 집합이어야 하는데 하나가 빠져 있었다(codex P1).** 채팅·A2A
  서빙·승인 재개엔 `impl_config`가 주입됐지만 **eval 입구엔 없었다** — 노드형/산출물형 평가가 기본
  단일 노드로 조용히 퇴화해 *실제 서빙과 다른 것을 채점*하고 있었다(316 이전부터 잠재, 317이 드러냄).
  같은 재료를 여러 입구가 조립하면 **입구를 한 곳에 열거·정합**해야 한다 — 하나라도 빠지면 그 입구만
  다른 것을 실행한다. → [[move-breaks-references-both-directions]]의 입구판, [[installed-guard-isnt-covering-guard]](가드가 아니라 주입의 커버리지).

- **에러 전파도 "모든 실행 입구"에서 같아야 한다 — 재개 경로가 500으로 샜다(codex P1).** 미등록 impl을
  채팅/서빙은 정직한 설정 오류로 처리하도록 고쳤는데, 승인 재개(`_rebuild_resume_graph`)는 내가 직접
  점검하다 발견(호출부가 None 가드 없이 tuple unpack → TypeError). **한 에러 클래스(AgentConfigError)를
  도입하면 그것을 던지는 build_graph의 *모든 호출부*를 세야 한다** — 네 곳(채팅·서빙·재개·eval)을 다
  고치고서야 정합. 자가 점검이 codex 전에 한 곳(재개)을 잡았고 codex가 다른 한 곳(eval)을 잡음.

- **인터페이스 하강은 상위 패턴을 그대로 미러하면 싸다.** register_node/get_node_impl/AgentConfigError
  재사용은 register_agent(085)의 판박이 — 새 개념(신뢰 경계·미해결=거부·eval 없음)을 재발명하지 않고
  "노드 수준"으로만 내렸다. 심지어 verify 구조(레지스트리·미등록·부트스트랩)도 085 미러. **잘 선 추상을
  한 단계 내리는 건 새 추상을 세우는 것보다 훨씬 싸다** — 경계·불변식·검증 골격이 딸려온다.

- **부팅 upsert도 동시성 자산이다 — 카탈로그 쓰기는 lock을 공유해야(codex P1).** sync_code_nodes의 고아
  정리(scan→delete)가 에이전트 저장(ref 검증)의 advisory lock과 직렬화 안 돼 dangling ref 창이 열렸다.
  "부팅 시 1회"라는 직관이 rolling deploy·수동 sync·멀티워커에서 깨진다. 316에서 도입한 이름 잠금을
  sync도 공유(발행·삭제·저장·동기화 네 경로가 같은 키). → [[hand-authored-migration-ids-collide-silently]] 계보(부팅 경로도 경합).

- **코드 노드는 prompt/model이 없다 — 부분 객체를 렌더하는 UI는 방어가 기본값이 아니라 분기다.** 316에서
  `n.tools ?? []`로 막았는데 317에서 같은 클래스(`n.prompt.trim()`)가 collapsed 헤더에서 또 터졌다(codex
  P2). `?? ''` 방어로는 부족 — 코드 노드는 아예 **다른 카드**(읽기 전용 안내)라 분기가 맞다. **타입이
  유니온이면(설정|코드) 렌더도 유니온 분기여야** 부분 필드 접근이 원천 차단된다.

## 검증 (사다리)
- **단위+통합**: `tests/verify_317_code_node.py` VERIFY317_OK — 레지스트리(등록/미등록/부적합)·
  mask_pii 결정성·normalize_nodes impl 통과·미등록=AgentConfigError·오버라이드 표면(_node_patch_fields·
  partial)·부팅 upsert(멱등·동일버전 덮어쓰기·kind 혼합 스킵)·API 발행/삭제 409·실행 마스킹 실측·
  고아 행 채팅 설정오류·**eval 입구(H6: 코드 노드 실행·고아 impl=error obs, codex P1)**.
- **UI 기능**: 프로브 PROBE317_UI_OK — 노드 메뉴 코드 Tag·"코드로 관리됩니다"·발행 버튼 없음·구현
  표시·오버라이드 서랍 코드 노드 카드 **JS 에러 0(codex P2 크래시 봉인)**.
- **적대(codex)**: P0 0·P1 3 수정(eval 입구·재개 500·sync TOCTOU)·P2 2 수정(kind 혼합 lock·UI 크래시).
- 회귀: 파이프라인 259/260/261/265/268/270/287·316·eval 119/137/240·HIL 041/116, ruff/mypy/tsc/vite 클린.

## 남은 것 / 주의
- **3탄(스펙 318 예정)**: 노드에서 에이전트 호출 — 브로커 kind=agent(로컬+A2A) 재사용, 이름
  `agent__{agent_id}`, 재귀 깊이 상한 필수. 노드형 확장 3부작의 마지막.
- OUT: 코드 노드 런타임 업로드/핫리로드(레포+배포로만)·agent-flow 코드젠 확장(수요 후)·per-노드
  오버라이드 세밀 검증 UI. 코드 노드의 임의 부수효과는 신뢰 레지스트리 전제(사용자 업로드 경로 없음).
- 고아 코드 노드(레지스트리에서 빠졌으나 참조 있음)는 보존+실행 시 설정 오류로 표면화(조용한 참조
  파괴보다 정직) — 참조 0일 때만 정리.
