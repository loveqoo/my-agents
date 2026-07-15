# 365 — 전면 개명은 초록 게이트 밖 표면으로 샌다 (자=전체 grep sweep)

**맥락**: `persona`→`prompt` 완전 개명(테이블·컬럼·API·config 키·백엔드/프론트 식별자·라벨). `make test`
SUITE_OK·tsc 0·verify_364 PASS로 초록인데도 잔재가 남았다. 초록이 개명 완결을 뜻하지 않았다.

## 샌 표면 (초록 게이트가 안 건드림)

1. **형제 패키지를 sweep에서 빠뜨림** — `packages/api`·`admin`만 개명하고 `packages/agent`(AgentBuildContext
   `persona` 필드)를 놓쳐, 런타임에 `__init__() got unexpected keyword 'prompt'`로 터짐. 단위/tsc는
   각 패키지 안에서 초록이라 경계 넘는 호출부(api→agent)만 깨졌다.
2. **e2e specs가 `make test` 밖·tsc 밖** — `tests/e2e/specs/*.ts`가 개명된 `/prompts` 대신 `/personas`를
   계속 호출. Playwright e2e는 make test 스위트에 없고 admin tsc 대상도 아니라 두 초록 모두 통과.
   개명 대상인데 **어떤 게이트에도 안 걸리는** 코드였다.
3. **생성 문서** — `admin/public/guide/index.html`은 `docs/guide/*.md`에서 `build-html.py`로 생성.
   산출물(html)만 고치면 재빌드 때 덮여 사라진다. 소스 md를 고치고 재빌드해야 하며, 임베드 스크린샷
   (`guide-blocks.png`)은 별도 재촬영 대상(구 라벨 노출 중).
4. **구동 중 서버의 stale 바이트코드** — editable-install이라도 `--reload` 없이 돌던 uvicorn은 인메모리
   + `__pycache__/*.pyc`를 잡고 있어 소스 개명 후에도 `/blocks`가 "페르소나"를 반환. `pkill -9` +
   `find … __pycache__ -exec rm -rf` + 재기동해야 새 코드 반영(브라우저 stale 오진의 진짜 원인).

## 도구 함정

- **한글 소스 리터럴은 `perl -Mutf8` 필수** — `-CSD`는 파일 I/O UTF-8만 처리하고 *프로그램 소스의* 한글
  리터럴(`s/페르소나/프롬프트/`)은 안 본다. `-CSD` 단독이면 한글 치환이 조용히 0건.
- **`persona`↔`personal` 오손** — `personal-secretary`가 "persona"를 포함. `[Pp]ersona(?!l)`로 보호.
- **단어 분해로 파일 유실** — `for f in $files`가 공백 split. `find -print0 | xargs -0`로.

## 교훈 (자를 먼저 만들어라)

개명의 자(ruler)는 **전 파일 타입·전 디렉터리 grep sweep**이지, 기억나는 패키지 몇 개가 아니다. 완료
판정은 "잔재 grep = 0(금지 목록·다른 개념·허용 잔재를 명시 열거하고 그 여집합이 0)"로 수치화한다.
초록 게이트(단위·tsc)는 *그 게이트가 실행하는* 코드만 본다 — e2e·생성문서·형제패키지·구동서버는
그물 밖이라, 개명은 게이트 통과가 아니라 sweep 0으로 닫힌다. 관련: [[move-breaks-references-both-directions]]
(참조는 양방향), [[installed-guard-isnt-a-covering-guard]](설치≠전범위 덮음).
