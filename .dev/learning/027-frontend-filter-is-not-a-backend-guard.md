# 027 — 프런트 필터는 백엔드 계약의 가드가 아니다

날짜: 2026-06-26
출처: 스펙 [025](../../docs/spec/025-playground-proxy-config-override.md) 타자 검증(codex P1)
연결: [[016-playground-proxy-config-override]], [[probe-deeper-before-concluding]]

## 교훈

클라이언트(프런트)에서 입력을 거르는 코드는 **UX 편의**일 뿐, 서버 측 불변식을 보호하지 않는다.
같은 엔드포인트를 직접 호출(curl, 다른 클라이언트, 미래의 코드)하면 필터를 우회한다. **입력 검증·
불변식 보호는 그 데이터를 실제로 소비하는 쪽(백엔드)에 둔다. 백엔드는 클라이언트를 신뢰하지 않는다.**

### 구체 사례 (spec 025)

- 의도: 빈 systemPrompt 오버라이드가 저장 persona를 지우면 안 됨.
- 실수: 프런트 `overridePayload`에서만 빈 값을 거름 → "프런트로는 안 가니 안전"이라 자가 결론.
- 결함: 백엔드 `_load_context`는 `"systemPrompt" in overrides`만 확인하고 빈 문자열도 persona에 덮어씀
  → 직접 API 호출이면 persona 소실. codex가 [P1]로 지적.
- 수정: 백엔드에 가드 — `sp = overrides.get("systemPrompt"); if isinstance(sp,str) and sp.strip(): persona = sp`.

## 적용 방법

- 프런트에서 "이런 값은 안 보낸다"는 필터를 짰다면, **같은 규칙을 백엔드에도** 둔다(또는 백엔드에만).
  프런트 필터를 백엔드 정확성의 근거로 삼지 말 것.
- "프런트가 막으니 백엔드는 신뢰해도 된다"는 생각이 들면 그게 신호다 — 그 불변식을 백엔드에서 검증하라.

## 운영 팁 — 타자 검증 사각: untracked 신규 파일

`codex review`/`codex exec`에 `git diff`로 변경을 넘기면 **untracked 신규 파일은 diff에 안 잡혀**
리뷰에서 통째로 빠진다(spec 025에서 `OverridePanel.tsx` 신규 파일이 그래서 P2로 빠짐). 타자 검증 줄 때:
- `git status`로 신규 파일을 먼저 확인하고, `git add -N <file>`(intent-to-add) 후 diff를 뜨거나
  diff에 신규 파일 내용을 명시적으로 포함한다.
- 핵심 로직이 신규 파일에 있으면 "이 파일은 diff에 없으니 따로 첨부"라고 챙긴다.
