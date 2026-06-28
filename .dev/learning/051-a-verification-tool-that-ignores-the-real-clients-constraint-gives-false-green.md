# 051 — 실 클라이언트의 제약을 무시하는 검증 도구는 거짓 green을 준다 — curl은 브라우저가 아니다

## 맥락
원격 어드민 로그인이 안 됐다(스펙 050 후속 트러블슈팅). curl로 로그인 라운드트립을 돌리니
login→204+Set-Cookie, `/users/me`→200 — **완벽히 green**. "서버는 건강하다"고 결론냈다. 그런데
브라우저에선 로그인이 안 잡혀 폼으로 튕겼다. 쿠키에 `Secure` 플래그가 있었고 사용자가 평문 http로
접속했기 때문이다 — 브라우저는 Secure 쿠키를 http(비-localhost)에서 *저장하지 않는다*. 그런데
**curl은 `Secure`를 무시**하고 어떤 스킴에서도 쿠키를 보낸다. 그래서 curl은 통과, 브라우저는 실패.

## 메타패턴
검증 도구가 **실제 클라이언트가 강제하는 제약을 모델링하지 않으면**, 그 도구 위의 green은 거짓이다.
도구는 "프로토콜이 동작하나"를 확인하지만, 실패는 "*그 클라이언트가 그 환경에서* 동작하나"에서 난다.
둘 사이의 간극 = 도구가 빼먹은 제약. 여기서 그 제약은 **Secure 쿠키는 HTTPS에서만 저장**이라는
브라우저 정책이고, curl엔 그 정책이 없다.

흔한 형태(검증 도구 < 실 클라이언트):
- **curl/httpx ↔ 브라우저**: Secure·SameSite·mixed-content·CORS preflight·third-party 쿠키 차단을
  curl은 강제 안 함. 인증/쿠키/origin이 끼면 curl green이 브라우저 실패를 못 잡는다.
- **단위 테스트 ↔ 실 런타임**: 인메모리 더블이 실 DB의 cascade·트랜잭션·동시성을 안 가짐(learning 040).
- **happy-path 시드 ↔ 적대 입력**: 행복경로만 태운 검증은 막은 척만 함(cap-the-raw-source,
  035 "초록 verify≠견고").

035·045가 "*초록이 견고를 보장 안 한다*"의 일반론이라면, 이건 **그 거짓 초록의 한 구체적 발생원 =
검증 도구의 *충실성 결핍*(도구가 실 클라이언트보다 관대함)** 축이다. 044(가드 범위)·046(timeout
span)와 달리 *대상 코드*의 결함이 아니라 *검증 수단*의 결함이다 — 코드는 옳고 도구가 거짓말한다.

## 적용점
- **인증·쿠키·origin·mixed-content가 끼는 경로는 curl green을 신뢰하지 말 것.** 최소한 실 브라우저
  (Playwright)로 한 번 태우거나, 도구가 그 제약을 강제하도록 맞춘다(예: https origin에서 테스트).
- 검증 전에 **"이 도구가 실 클라이언트의 어떤 제약을 빼먹나?"**를 묻는다. 빼먹는 제약이 결함의
  발생 가능 지점이면, 그 도구의 green은 그 결함에 대해 무의미하다.
- 도구를 못 맞추면(원격 사용자만 실 클라이언트를 가짐) **헤더/설정 레벨로 결함을 좁혀 두고**(예:
  Set-Cookie에서 Secure 제거를 실증) 실 클라이언트 확인은 마지막 1회로 끝낸다.
- verification ladder(memory: verification-ladder-three-rungs)에 **"각 rung을 어떤 *도구*로 태우나,
  그 도구가 실 환경 제약을 재현하나"**를 명시적으로 넣는다.

관련: 035(초록 verify≠견고), 040(단위 도구가 못 보는 통합 결함), 045(self-fixture),
cap-the-raw-source-not-the-buffer(happy-path 거짓 초록), [[verification-ladder-three-rungs]].
