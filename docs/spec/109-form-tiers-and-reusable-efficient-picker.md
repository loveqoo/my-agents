# 109 — 폼 3단계 재편 + 재사용 효율 피커(등록 폼 + 플레이그라운드 오버라이드)

## 배경 / 왜

스펙 108(유저언어·종류 분기) 후에도 사용자 지적:
- **필수/공통 vs 종류별/선택이 안 나뉘어** 모든 필드가 같은 무게로 평평하다 → 뭘 꼭 정하고 뭘
  나중에 손봐도 되는지 안 보인다. (사용자 확정: AskUserQuestion "3단계 + 세부설정 접기".)
- **늘어나는 항목(RAG·MCP·에이전트·권한·메모리)을 효율적으로 렌더**하고 알아보기 쉽게 해야 한다.
  (직접 응답 자원칸은 아직 평평한 체크박스 — 스펙 107 접이식이 조율형 위임에만 적용됨.)
- **같은 개선을 플레이그라운드 오버라이드에도** 반영해야 한다(`OverridePanel.tsx` — memories·mcps가
  평평한 체크박스 2개).

## 목표

1. **재사용 효율 피커 컴포넌트**(`PickerGroups`)를 만들어 등록 폼·오버라이드 **둘 다** 쓴다.
   - 종류별 접이식(antd Collapse) + 헤더 `선택/전체` 카운트 + 항목 많으면(>6) 패널 내 검색 +
     선택 있는 그룹 기본 펼침(스펙 107 패턴을 컴포넌트로 추출). 항목이 늘어도 폼 높이 안정.
2. **등록 폼 3단계 재편**(`AgentsView.tsx`):
   - **기본(필수)**: 이름*·종류(직접응답/조율형)·모델·페르소나.
   - **이 에이전트가 하는 일**(종류별, `PickerGroups`): 직접응답=도구·문서·기억·권한,
     조율형=다른 에이전트·도구·문서·사용자 기억.
   - **세부 설정(선택·접힘)**: Temperature·채팅 히스토리·대화 저장.
3. **오버라이드 일관화**(`OverridePanel.tsx`): 같은 원칙 적용 — memories·mcps를 `PickerGroups`로,
   Temperature·historyDepth는 "세부 설정" 접이식으로. model·페르소나/systemPrompt는 상단 기본.

## 설계

### 재사용 컴포넌트 `PickerGroups` (`admin/src/PickerGroups.tsx`)
- props: `groups: {key,title,items:{id,label,hint?,extra?}[],emptyText?}[]`, `selected: string[]`,
  `onToggle:(id)=>void`, `searchThreshold=6`.
- 렌더: antd `Collapse` — 그룹당 패널, 헤더=`제목 + <Tag>선택/전체</Tag>`, 본문=(항목>임계면 검색
  `Input`)+체크박스 목록(항목 `hint`=회색 보조줄, `extra`=라벨 뒤 노드[권한 승인자 태그 등]).
  `defaultActiveKey`=선택 있는 그룹. 검색어는 컴포넌트 내부 state(그룹별).
- 두 소비처가 **같은 컴포넌트**를 써 렌더·검색·카운트 로직 drift 0.

### 등록 폼(AgentsView) 소비
- direct 그룹 items에 기존 리치 렌더 보존: 권한→`extra`(승인자 Tag), 메모리→`hint`(설명), 컬렉션→
  `hint`(임베딩·청크). 조율형 그룹은 평문 라벨(108 그대로).
- 세부 설정은 별도 `Collapse`(단일 패널 "세부 설정", 기본 접힘)로 Temperature·히스토리·대화저장.

### 오버라이드(OverridePanel) 소비
- memories·mcps → `PickerGroups`(그룹 2개: 기억·도구). Temperature·historyDepth → "세부 설정" 접이식.
- `Overrides` 타입·`overridePayload` diff·적용 흐름 **무변경**(표현 계층만). model/systemPrompt 상단 유지.

## 검증

- **브라우저(직접)**: 등록 폼 — (a) 3단계 그룹 보임(기본/하는 일/세부설정), 세부설정 기본 접힘.
  (b) 종류 바꾸면 "하는 일" 그룹 세트가 바뀜(직접=도구·문서·기억·권한, 조율형=다른에이전트·도구·문서·
  사용자기억). (c) 그룹 접이식·카운트·검색 동작. (d) 저장 왕복(직접·조율형 각각). 오버라이드 —
  (e) memories·mcps가 접이식 카운트로, temperature·history가 세부설정에. (f) 오버라이드 적용 diff 무회귀.
  두 곳 스샷.
- 무회귀: 저장/적용 모델·API 무변경. 108 브라우저 검증(내부어·기술 id 부재) 유지.

## 비목표 (OUT)

- 리스트 가상화(virtualization) — 검색+접이식으로 충분(수백 이하). 수천 되면 후속.
- 오버라이드에 capabilities/impl 노출 — 소관 아님(종류·위임은 등록 시 결정).
- 다른 폼(빌딩블록 등) 재편 — 이번은 등록 폼 + 오버라이드.
