# 338 — 사고 과정 표시(스펙 410)

## 발단
개발자 "thinking 모드일 때 플레이그라운드에서 과정을 잘 보여주나? 체크했나?" → 안 했었다. thinking을
켜는 배관(408/409)만 만들고 사고를 *보여주는* 것은 안 만들었다 — 또 배관에서 멈춤([[ui-verification-must-be-functional]]).

## 가장 큰 교훈 — 조사가 직접 프로브보다 싸다 (개발자 조언)

처음에 "스트리밍은 사고를 잘라낸다"고 오진하고 **25번+ 직접 프로브**로 헤맸다. 여러 프롬프트를 섞어
측정해 **모델의 확률적 사고를 체계적 결함으로 오독**했다(direct는 사고/graph는 안 함처럼 보였으나,
실은 "직접 먼저→그래프 둘째" 순서라 MLX 연속요청이 둘째를 억제한 것 + 프롬프트별 사고 확률 차이).

**개발자 "다른 플랫폼이 어떻게 푸는지 조사하라, 직접 테스트는 비싸다"가 전환점.** 조사(서브에이전트)가
즉시 "서버 reasoning 파서 미설정" 신호를 짚었고(vLLM `--reasoning-parser`가 표준), **2번의 값싼
확인**(`ps`로 기동 플래그·`serve --help`)으로 근본 원인 확정: rapid-mlx가 `--reasoning-parser qwen3`
**없이** 떠 있어 스트리밍에서 `<think>`를 `reasoning_content`로 분리하지 않았다. 파서 추가 후 스트리밍
델타에 사고가 실린다(실증: 1274개 델타·3599자 실시간).

**후크**: 재현 불가·murky한 원격 동작은 **직접 프로브 전에 선행 사례 조사**. 25 프로브 ≫ 1 조사+2 확인의
비용. [[observe-before-remedy-remote-env]]의 확장 — "관측"에 *다른 사람들이 이미 관측한 것*을 포함하라.

## 두 번째 교훈 — 인프라(서버 설정)를 코드보다 먼저 의심

내 클라이언트 코드(ReasoningChatOpenAI 서브클래스)는 **처음부터 맞았다**(단건에선 이미 사고를 잡음).
막힌 건 **서버가 스트리밍 reasoning을 안 켠 것**. "우리 코드가 뭘 잘못했나"만 파다 서버 설정을 늦게
봤다. 미검증 전제("서버는 제대로 줄 것") 위에서 코드를 의심하면 엉뚱한 데를 판다([[verify-premise-before-designing]]).

## 세 번째 교훈 — 축 분리 불변식은 무조건이어야 (codex P1)

스펙이 "reasoning 영속 0"을 **무조건 불변식**으로 선언했는데, 구현은 "서버가 깔끔히 분리할 때만"
만족했다. 파서 없는 서버가 `<think>`를 content에 인라인하면 acc→영속으로 샜다. **관문 정화**로 봉합:
`full`(영속 본문) 조립 지점에서 `strip_reasoning_blocks`로 `<think>...</think>`(종결·미종결) 제거 —
서버 종류와 무관하게 불변식 성립([[gate-cleanse-at-chokepoint]], 스펙 407 동형). *조건부 기능*과
*무조건 불변식*을 한 스펙에 담으면, 불변식은 여집합(파서 없는 서버)까지 방어해야 한다.

## 무엇을 했나

- **ReasoningChatOpenAI**(langchain-deepseek `ChatDeepSeek` 동형): base ChatOpenAI가 버리는
  reasoning_content를 `_create_chat_result`(비스트리밍)+`_convert_chunk_to_generation_chunk`(스트리밍
  델타)로 additional_kwargs에 살림. 필드명 관대(reasoning_content/reasoning/thinking — 서버·버전마다 갈림).
- **분리 SSE 채널**: reasoning은 본문과 별개 프레임, 영속·메모리·trace 본문 불포함(축 분리). 관문 정화로
  파서 없는 서버의 인라인 `<think>`도 영속서 제거.
- **@ant-design/x `Think`** 접이식 패널 + `onReasoning` 스트리밍 누적 → 실시간 사고 표시.
- 스트리밍이 표준(단건 강제 불필요) — 서버 파서 켜면 타임아웃·억제 우회.

## 검증
verify_410 14/14(추출·축분리·관문정화 종결/미종결/통과)·verify_076 재활(ReasoningChatOpenAI 패치)·
브라우저 e2e VERIFY410_BROWSER_OK(Think 패널 실시간 스트리밍 스샷)·서버 raw 실증·codex 2패스
(P1 관문정화·P2.1 model_dump exclude·P2.3 독립 if; P2.2는 오판=isStreaming 이미 isLast 게이트).

- **그물 잔여 플레이크 주의**: 이번 세션 25+ 프로브·e2e가 dev DB에 잔재(세션/메시지)를 남겨 make test가
  매 실행 다른 db층 테스트를 red로(격리 통과=환경). verify_124는 **커밋된 상태서도** 실패(실모델 랭킹
  비결정 선재 플레이크, 내 변경과 무관 — stash로 확인). 근본=fresh-DB-per-run 격리 하네스(백로그 대형).
