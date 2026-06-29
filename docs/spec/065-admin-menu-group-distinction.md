# 065 — 어드민(슈퍼유저) 메뉴를 그룹 헤더로 구분

## 배경 / 문제
사용자 제안: "어드민 기능과 아닌 것은 메뉴에서 구분하는 게 어때?"

현 `AdminShell.tsx`의 사이드바 메뉴는 슈퍼유저 전용 항목(유저·배치·허용 호스트)을
`user.is_superuser` 게이트로 **노출 여부**는 이미 분리하지만(비-슈퍼유저에겐 안 보임),
일반 작업 항목(개요·에이전트·…·승인) 뒤에 **평면(flat)으로 append**돼 있어
시각적으로 어디까지가 일반 기능이고 어디부터가 관리자 기능인지 **경계가 없다**.
반면 "도구"(Playground)만 `type:'group'` 헤더로 구분돼 있다.

## 목표
슈퍼유저 전용 항목을 **"관리자" 그룹 헤더**로 묶어, 일반 작업 메뉴와 시각적으로
구분한다. 이미 in-file에 존재하는 "도구" 그룹 패턴(`type:'group'` + collapsed 시 라벨 숨김)을
그대로 차용한다 — 새 의존성·새 패턴 도입 없음.

## 비목표
- 권한/노출 로직 변경 없음(기존 `user.is_superuser` 게이트 유지 — 메뉴 노출은 UX 편의일 뿐
  서버 라우터가 `require("...","manage")`로 독립 강제, spec 064 §D5).
- 일반 작업 항목은 그룹 헤더 없이 둔다(기본 워크스페이스 = 헤더 없는 상단 묶음).
  굳이 "운영" 헤더를 새로 달면 노이즈 — "관리자" 헤더 하나가 경계를 명확히 한다.
- role 기반 세분화 노출은 추후(현 1차 게이트는 슈퍼유저 단일 축).

## 설계 (D1)
`menuItems`에서 슈퍼유저 분기를 **평면 항목 배열 → 단일 그룹 항목**으로 바꾼다:

```tsx
...(user.is_superuser
  ? [
      {
        type: 'group' as const,
        label: collapsed ? '' : '관리자',
        children: [
          { key: 'users', icon: <TeamOutlined />, label: '유저' },
          { key: 'batch', icon: <ScheduleOutlined />, label: '배치' },
          { key: 'allowed-hosts', icon: <SafetyCertificateOutlined />, label: '허용 호스트' },
        ],
      },
    ]
  : []),
```

- collapsed(72px) 시 라벨 숨김은 "도구" 그룹과 동일 처리(`collapsed ? '' : '관리자'`).
- 그룹 children의 `key`/`icon`/`label`은 기존 값 그대로 — `views`/`selectedKeys`/`onSelect`
  배선 무변경(키 문자열 동일).
- ViewKey union·TITLES·views 맵 변경 없음.

최종 메뉴 시각 순서:
1. (헤더 없음) 개요·에이전트·빌딩 블록·프로바이더·모델·RAG 컬렉션·세션·메모리·승인 — 일반 작업
2. **관리자** (슈퍼유저만): 유저·배치·허용 호스트
3. **도구**: Playground

## 검증
- 브라우저: 슈퍼유저 세션으로 사이드바 캡처 → "관리자" 그룹 헤더가 슈퍼유저 항목 위에
  뜨고, 일반 항목과 시각 분리되는지 눈으로 확인(spec 064 shot 패턴 재사용). collapsed 토글
  시 헤더 숨고 아이콘만 남는지 확인.
- 회귀: 그룹 children 클릭 시 해당 뷰로 전환되는지(키 배선 무변경 확인).
- 타입체크: `tsc`(admin) 무에러.

## 완료 조건
- [x] D1 적용 — 슈퍼유저 항목이 "관리자" 그룹으로 묶임. → AdminShell.tsx:127-142 슈퍼유저 분기를
      평면 배열→단일 `type:'group'`("관리자")으로 교체.
- [x] 브라우저 캡처로 그룹 헤더 + 일반/관리자 시각 분리 확인. → `shot-admin-menu-065.mjs`
      `GROUP_TITLES ["관리자","도구"]`, 확장 샷에서 유저·배치·허용 호스트가 "관리자" 헤더 아래
      묶여 일반 작업 메뉴와 분리. collapsed 샷 `ADMIN_LABEL_WHEN_COLLAPSED 0`(라벨 숨김, 아이콘만).
- [x] 그룹 항목 클릭 → 뷰 전환 회귀 없음. → `STEP4_GROUP_ITEM_NAV_OK`('유저' 클릭 시 헤더 h3='유저').
- [x] admin 타입체크/빌드 무에러. → `npx tsc --noEmit` TSC_EXIT:0.

## 검증 사다리
- 브라우저 실측(`shot-admin-menu-065.mjs`): 그룹 헤더 렌더 단언 + 확장/collapsed/그룹-항목-네비 3샷.
- 타입체크(`tsc --noEmit`): 무에러.
- 자가검증 충분 판단(타자 적대 스킵) — 순수 표현 변경(메뉴 항목 배열을 그룹으로 재배치)이고
  권한/노출/배선(키·views·게이트) 무변경, 비가역·보안 표면 없음. 064 같은 파괴/보안 경로가 아니라
  codex 적대 rung 불필요(합의 규칙 "검증은 작업 성격에 맞게").
