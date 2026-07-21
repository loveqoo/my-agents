# 410 — 사고 과정 표시(thinking process display)

> 상태: **완료** · 2026-07-20 · verify_410 9/9 + 브라우저 e2e(Think 패널 실시간 스트리밍) + 서버 스트리밍 reasoning 실증(델타 1274개·3599자)
> 발단: 개발자 "thinking 모드일 때 플레이그라운드에서 과정을 잘 보여주나? 체크했나?" → 안 했었다.
> **진단 여정(중요)**: 처음엔 "스트리밍은 사고를 못 실는다"고 오진했다(측정을 여러 프롬프트로 섞어
> 확률적 사고를 체계적 결함으로 오독 — 25+ 프로브 낭비). **개발자 조언 "다른 플랫폼이 어떻게 푸는지
> 조사하라, 직접 테스트는 비싸다"가 전환점**: 조사가 즉시 "서버 reasoning 파서 미설정" 신호를 짚었고,
> 2번의 값싼 확인(ps로 기동 플래그·`serve --help`)으로 근본 원인 확정.
> **진짜 원인**: rapid-mlx가 `--reasoning-parser qwen3` **없이** 떠 있어 스트리밍에서 `<think>`를
> `reasoning_content`로 분리하지 않았다. 파서 추가 후 스트리밍 델타에 `reasoning_content`가 실린다
> (raw 실증: 순서 R→C, 사고 2542자 먼저 스트리밍). LangChain base `ChatOpenAI`가 그 필드를 버리는 건
> 별개 문제(소스 명시: "use a provider-specific subclass").

## 설계

### 원칙(연구·실측으로 확정)
- **스트리밍 reasoning이 표준** — 서버가 reasoning 파서(vLLM/SGLang/llama.cpp/rapid-mlx의
  `--reasoning-parser`)를 켜면 사고가 `delta.reasoning_content`로 **실시간 스트리밍**된다. 단건 강제
  불필요(타임아웃·억제 우회). 표시는 "reasoning 델타가 오면 누적 렌더"로 디커플 — 서버·필드명 무관.
- **서버 요구사항**: rapid-mlx는 `--reasoning-parser qwen3` 기동 플래그 필요(파서 없으면 스트리밍에
  사고 미노출). 다른 서버는 각자 파서 플래그(문서 참조). 이건 모델 인프라 설정.

### P1 백엔드 — reasoning 추출(LangChain이 버리는 걸 되살림)
- **provider-aware 서브클래스**(`ReasoningChatOpenAI`): `ChatOpenAI` 상속, `_create_chat_result`(비스트리밍)
  +`_convert_chunk_to_generation_chunk`(스트리밍 델타) override로 raw reasoning를
  `additional_kwargs["reasoning_content"]`로 실어 준다(langchain-deepseek `ChatDeepSeek`와 동형 패턴).
- **필드명 관대**: `reasoning_content`/`reasoning`/`thinking` 모두 읽는다(서버·버전마다 갈림 — vLLM
  최신은 `reasoning`으로 개명). `build_chat_openai`(정본 팩토리)가 이 서브클래스를 항상 쓴다(사고
  없으면 키 부재라 무해). 스트리밍 델타 실증: 1274개 델타로 3599자 누적.

### P2 SSE — 사고를 본문과 분리된 채널로
- 사고 과정은 **답변이 아니라 과정** → 본문 sink(`_content_text`)는 지금처럼 content만 정화(reasoning
  불포함 유지 — 오염 0). reasoning은 **별도 SSE 프레임**(`data: {"reasoning": "..."}`)으로 흘린다.
- **축 분리 계약(스펙 407 동형)**: reasoning은 **영속·메모리·trace 본문에 안 들어간다**(표시 전용
  side channel). 자동저장·회상은 원발화·답변만 본다(사고 과정은 기억이 아니다).
- 스트리밍 reasoning은 델타로 다회 프레임(클라가 누적), 단건은 완성 후 1회 — 양쪽 같은 프레임 형식.

### P3 프론트 — @ant-design/x `Think` 패널
- 답변 말풍선 위에 접이식 **`<Think title="사고 과정">`**(@ant-design/x 2.8.0). props: `loading`=사고
  생성 중·`blink`=스트리밍 표시·`defaultExpanded={false}`(기본 접힘, 답변이 주인공)·내용은 마크다운
  렌더(MessageContent 재사용). 스트리밍이면 델타가 쌓이며 **실시간** 사고가 흐른다(실증 스크린샷).
- `streamChat` 클라가 `reasoning` 프레임을 `onReasoning`으로 누적해 메시지 `reasoning` 필드에 붙인다.
  DebugChat이 reasoning 있으면 Think 패널 렌더.

### P4 안내(능력·설정 연동)
- thinking 설정 근처(스펙 409 CapabilitySettings)에 "Thinking을 켜면 사고 과정이 대화에 접이식
  패널로 표시됩니다(서버가 reasoning 파서를 지원할 때)" 안내. 강제 전환 없음(사용자 선택).

## OUT
- reasoning 토큰 예산·길이 캡(사고가 매우 길 때) — 표시 캡은 P3에 최소만, 정밀 예산은 후속.
- `ThoughtChain`(다단계 사고 체인 시각화)은 노드형/조율형 확장 후속(직접형은 `Think` 하나로 충분).
- 모델의 확률적 사고(같은 프롬프트도 사고 여부 갈림)는 모델·서버 특성 — 우리 표시는 사고가 오면
  보여줄 뿐(강제 못 함).

## 완료 기준
- [x] thinking 응답에서 reasoning가 백엔드까지 도달(서브클래스 추출 — 스트리밍 델타·비스트리밍 양쪽) — verify_410 9/9.
- [x] SSE reasoning 프레임이 본문과 **분리**(본문·영속·메모리엔 reasoning 불포함 — 축 분리) — verify_410 U3.
- [x] 플레이그라운드에서 실제 thinking 응답에 `Think` 패널이 뜨고 사고가 **실시간 스트리밍** — 브라우저 e2e VERIFY410_BROWSER_OK.
- [x] 서버 스트리밍 reasoning 실증(`--reasoning-parser qwen3` 적용 후 델타 1274개·3599자).
- [ ] make test SUITE_OK(배타) + codex 적대 리뷰(축 분리 누수·서브클래스 회귀·본문 오염).
