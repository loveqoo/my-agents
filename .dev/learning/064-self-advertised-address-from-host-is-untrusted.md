# 064 — 서버가 *자기 주소를 스스로 광고*할 때 그 주소를 요청 Host에서 끌어오면 공격자 입력이다

**언제**: 서버가 자신을 가리키는 절대 URL을 *생성해서 밖으로 내보낼* 때 — A2A/Agent 카드의 서비스
`url`, OAuth `redirect_uri`, 웹훅 콜백 등록, SSO 메타데이터(ACS/issuer), 비밀번호재설정/검증 링크,
`Location` 리다이렉트. 특히 그 self-base를 `request.base_url`/`Host`/`X-Forwarded-Host`처럼
**요청에서 파생된 값**으로 채울 때.

**명제**: `Host` 헤더(및 그 파생 `request.base_url`)는 *클라이언트가 보낸 임의 문자열*이다 —
가상호스팅 라우팅용일 뿐 신뢰 출처가 아니다. 그 값이 서버가 *되돌려 광고하는* 자기 URL로 흘러
들어가면, 공격자는 `Host: attacker.example`로 그 광고를 자기 호스트로 돌릴 수 있다. 그 광고 URL이
이후 *인증된* 호출의 목적지가 되면(카드 url로 메시지 전송, redirect_uri로 토큰 전달) **프롬프트·
Bearer 토큰·인가 코드가 공격자에게 샌다**. self-base는 **신뢰 경계**다.

**표본**: 스펙 061 `a2a_server._self_base`. 노출 ui 에이전트의 A2A 카드 `url`(=JSON-RPC 호출
엔드포인트로 connect가 저장)을 `request.base_url` 폴백으로 구성했다. codex 적대리뷰 H1(High):
`Host: attacker.example` → 카드 `url`=`http://attacker.example/agents/<id>/a2a` → 이후 클라가 그
주소로 머신토큰 Bearer + 프롬프트를 전송 → 탈취. 스펙 §5가 *가능성은 예상*했지만 폴백을 그대로
뒀고, 적대자가 *구체적 입력으로 실증*하고서야 고쳤다(retrospect 049 통찰4: 예상된 위험도 구체화되면
그 자리에서 싸게 고친다).

**처방**:
1. **명시 설정을 1순위 신뢰 출처로.** env(`A2A_SELF_BASE_URL` 같은 운영자 선언 절대 URL)가 있으면
   그걸 쓰고 Host 파생은 *무시*한다. 프록시 뒤 표준 패턴(Django `ALLOWED_HOSTS`+`USE_X_FORWARDED_HOST`,
   Rails `default_url_options[:host]`, OAuth는 *사전등록* redirect_uri 정확매칭).
2. **Host 파생 폴백은 로컬/사설로만 fail-closed.** env 없이 공인 Host로 들어온 요청은 광고 URL을
   서빙하지 말고 거부(503)해 운영자가 self-base를 명시하도록 강제. 루프백 dogfood(127.0.0.1)·
   Tailscale(100.x)만 폴백 통과 — `net_guard.host_is_private(host)`(resolve가 전부 비-global일 때만
   True, 공인 IP 하나라도 섞이거나 resolve 실패면 False=보수적).
3. **사전등록 화이트리스트가 더 강하다.** 자유 입력 Host를 정규화하느니, 허용 self-base 집합을
   *선언*하고 정확매칭(redirect_uri 모델). 정규화는 우회 표면을 남긴다.

**판별**: "이 응답에 들어가는 *내 주소*를 어디서 가져왔나?" — 요청(Host/base_url/X-Forwarded-*)이면
오염 가능. "그 주소가 이후 *인증된* 트래픽의 목적지가 되나?"면 누출 경로 성립. 둘 다 yes면 신뢰
경계로 다뤄 env/화이트리스트로 못 박는다.

**가족**: 063(fail-closed 가드는 위반값+조치예시를 담아라 — H1 503 메시지도 "A2A_SELF_BASE_URL을
이 서버 절대 URL로" 처방 담음)·044/057의 redirect-SSRF(아웃바운드 리다이렉트 추종 차단)와 *대칭*:
redirect-SSRF는 *내가 따라가는* 주소가 오염, 이건 *내가 광고하는* 주소가 오염. installed-guard-isnt-
covering-guard(검사지점≠부수효과지점)와 공통뿌리 = **신뢰 못 할 입력이 보안 결정값으로 흐르는
경로를 따라가라**. happy-path(정상 Host)는 초록이라 자가검증이 구조적으로 못 봄 → 타자(codex) 적대
필수.
