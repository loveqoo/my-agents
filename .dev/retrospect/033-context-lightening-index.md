# 033 — 컨텍스트 경량화 회고 (스펙 043)

> 지배 스펙: `docs/spec/043-context-lightening-index.md`. 관련 learning: [[042-a-move-breaks-references-in-both-directions]],
> [[035-guard-the-source-not-the-copy]], [[040-real-infra-integration-catches-glue-and-deployment-drift]].
> 발단: 사용자가 "Context 단계 통독 → compaction 잦아짐" 보고.

## 무엇을 했나

자산 115개(spec 42·learning 41·retrospect 32, ~708KB)가 쌓이며 Context 단계의 **full 통독**이
compaction을 당겼다. 메모리(`MEMORY.md`)는 이미 "한 줄 인덱스 → 필요한 1개만 full"로 가볍게
도는데 자산엔 그 층이 없던 게 근본 원인. 같은 패턴을 자산에 입혔다:

- **L1**: `INDEX.md` 3종 신설(learning 41·retrospect 32·spec 43=루트34+아카이브9). 항목당 한 줄
  `NNN 제목 — 후크 [키워드]`. 서브에이전트 3개 병렬 생성.
- **L2**: `CLAUDE.md` Context 규칙을 "grep해 full 통독" → "**INDEX 먼저, 후크 불충분 시만 full**"로
  교정(§2·빠른합의·§6 Compounding의 인덱스 갱신 의무까지).
- **L3**: 완료 로드맵 스펙 034~042를 `docs/spec/archive/`로 이동, 들어오는 참조 9곳 갱신.

효과: Context 진입 읽기량 **약 95% 감소**(532KB 통독 상한 → 25KB 인덱스 우선).

## 사람과 합의한 분기

범위를 AskUserQuestion으로 물어 **L1+L2+L3**(L4 물리통합 보류) 선택. L4(중복 learning 통합)는
원문 손실·재작성 리스크라 인덱스 "관련 묶음"으로만 완화하고 물리 통합은 후속으로 남겼다 — "큰
결정은 사람과, 손실 위험은 보수적으로".

## 적대 리뷰가 잡은 것 — "이동은 양방향으로 참조를 깬다"

L3에서 *들어오는* 참조(다른 파일 → archive)만 갱신하고, **옮겨진 파일이 *내보내는* 상대링크**
(`archive/034·035·036` → 루트 `033·019·008·010·013`)를 놓쳤다. 8개 링크가 `archive/033...`로 깨졌다.
- 자가검증 스크립트도 같은 방향만 봤다: (d) 정규식이 `docs/spec/NNN-` 접두 참조만 검사 → 깨진
  나가는 상대링크를 못 보고 **green**. learning 035/040의 "초록 verify ≠ 견고" 재현.
- 수정: 번호로 분기(034~042=`./` 유지, 그 외=`../`)해 링크 교정 + 검사 (e)(archive 나가는 상대링크
  resolve) 추가. → learning 042로 일반화.

## 작게 헛디딘 것

- **zsh 단어분할**: `for f in $FILES`(여러 줄 변수)가 zsh에선 분할 안 돼 전체가 한 인자로 들어가
  perl이 "Can't open". → 배열 `files=(...)` + `"${files[@]}"`로 교정. (bash 가정의 함정, 코드버그 아님.)

## 다음에 가져갈 것

- **새 자산을 만들면 같은 턴에 해당 `INDEX.md`에 한 줄 추가**(이미 §6에 규칙화·이 회고로 도그푸딩).
  누락은 `verify_043_index.py`(줄수=파일수)로 사후 탐지. 반복 누락 시 Scaffolding 훅으로 승격(빚).
- **이동·리네임은 양방향 참조를 깬다** — 들어오는 것만 고치면 절반. 검증도 양방향을 봐야 green이
  견고(learning 042).
- 인덱스 후크가 원문을 왜곡하면 잘못된 스킵을 부른다 — 사용 중 어긋나면 그 자리서 교정(Context의
  "오래된 기록 교정" 책무).
