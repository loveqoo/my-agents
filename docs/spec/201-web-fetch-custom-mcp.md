# 201 — web-fetch 커스텀 MCP (위키피디아 검색·본문) + 능력 부여 도그푸딩

## 배경 (사용자 제안)
"웹 검색 기능 하나 만들고 '능력'을 부여해보자" → 제공자 논의에서 사용자가 **패치 방식** 제안:
검색엔진 HTML 파싱 대신 "위키피디아 검색이면 위키 주소를 만들어 패치". 위키는 공식 조회 API가
있어 주소 조립→JSON 응답으로 더 안정적. 스펙 200에서 개편한 '능력 부여' UI의 실사용 검증(도그푸딩)
을 겸한다.

## 설계

### A. 도구 — served_mcp.py 신뢰 레지스트리에 `web-fetch` 추가 (스펙 156 패턴)
- **`wiki_search(query, limit=5, lang='ko')`** — `GET {lang}.wikipedia.org/w/api.php?action=query&
  list=search…` → 제목+스니펫(태그 제거) JSON.
- **`wiki_page(title, lang='ko')`** — `GET {lang}.wikipedia.org/api/rest_v1/page/summary/{title}`
  → 요약 본문(extract) JSON.
- 확장 여지: 같은 패턴(사이트별 주소 조립→패치)으로 타 사이트 추가 가능 — 이번엔 위키만.

### B. 안전 (무인증 공개 서빙 + 아웃바운드)
- **호스트 고정**: `lang`은 `{ko,en}` allowlist — 임의 호스트 조립 불가(SSRF 없음, 사용자 입력은
  검색어·제목뿐이고 URL 경로/쿼리로만 들어감).
- **캡**: 타임아웃 8s · 응답 raw 바이트 캡(512KB, [[cap-the-raw-source-not-the-buffer]] — 초과 시
  에러 반환) · limit≤10 · 스니펫/본문 길이 캡.
- **read-only**: 조회 전용 → `_SIDE_EFFECT_FREE_TOOLS` 등록(부팅 불변식 통과). 오류는 raise 대신
  `{error}` JSON(graceful).
- User-Agent 명시(위키 API 요구).

### C. 등록·배선 (코드 0줄 추가 경로)
- `_DEFS`에 넣으면 시드 **멱등 reconcile**(seed.py:362, 스펙 156)이 재기동 시 McpServer 행
  (source=custom, url=served_url) 자동 등록.
- 내부 사용도 served URL 경유(runtime.build_mcp_tools→MultiServerMCPClient)라 **published=True 필요**
  (미공개=서빙 게이트 404). 관리자가 드로어에서 공개 토글.

### D. 도그푸딩 — 능력 부여 실사용
- 새 '능력 부여' 탭에서 **member에게 `도구 · web-fetch` 부여**(실부여 유지 — 테스트 픽스처 아님).
- 에이전트 실검증: 플레이그라운드에서 web-fetch 배선(오버라이드 or 에이전트 설정) 후 위키 질의 →
  도구 호출·결과를 인스펙터/트레이스로 확인(기본 chat이 mock이면 도구 직접 호출로 대체하고 명시).

## 후속 (2026-07-07, 사용자 질문 "발동 조건을 알 수 없다")
- 발동 단어는 원래 없음(모델이 요청↔설명문 대조로 판단) — 설명문이 빈약해 불안정·불투명했다.
- **도구 docstring에 "이럴 때 사용" 명시**(위키/백과사전 요청·사실 질문·search→page 순서). 이 설명문은
  모델 라우팅 재료이자 MCP 상세 드로어의 사람 안내 — 한 문서로 둘 다 해결(회고 187 보류 건의 정공법).
- **reconcile 확장**: 기존 custom 행의 코드 소유 필드(tools·tools_meta·url)만 동기화, 관리자 소유
  (published·alias·enabled_tools) 보존 — 화면과 모델이 같은 설명을 보게(드리프트 봉합).
- 실증: "위키" 단어 없이 "백과사전에서 '세종대왕'을 찾아서" → wiki_page 550ms 호출·정답.

## RBAC 경계 (트리거 판정)
- **비트리거**: 유저별 데이터 무접촉. 새 도구는 read-only 조회. 공개 서빙은 스펙 156 안전 불변식
  (순수 도구 allowlist 부팅 강제) 그대로. 능력 부여는 기존 grantPolicy(admin 전용) 사용.
- 공개 시 `/_served/mcp/web-fetch/`는 무인증 — read-only 위키 조회라 수용(calc-tools 동형). 남용
  (프록시화) 캡은 타임아웃·바이트 캡·limit으로 완화. 레이트리밋은 OUT.

## 검증 (사다리)
1. **단위(mock transport)**: lang allowlist 거부·바이트 캡 초과 에러·limit 클램프·태그 제거·오류
   JSON(네트워크 불요, httpx.MockTransport).
2. **통합(live)**: 실 위키 API로 wiki_search/wiki_page 왕복(네트워크 best-effort — 실패 시 스킵 명시).
3. **e2e(UI)**: 재기동→web-fetch 행 자동 등록 확인→드로어에서 도구 메타 노출→공개 토글→능력 부여
   탭에서 member에 부여(문장·목록 확인, 실부여 유지)→플레이그라운드 실검증.

## 경계
- 타 사이트 확장·범용 URL 패치(허용 호스트 게이트 필요)·레이트리밋·검색엔진(DDG/Tavily)은 OUT.
- ko/en 외 언어는 OUT(allowlist 확장은 한 줄).
