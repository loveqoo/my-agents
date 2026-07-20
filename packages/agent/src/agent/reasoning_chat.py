"""reasoning_content를 살리는 ChatOpenAI 서브클래스(스펙 410).

langchain-openai base ChatOpenAI는 provider별 비표준 필드(reasoning_content)를 **추출하지 않는다**
(소스 명시: "not extracted — use a provider-specific subclass", langchain-openai 1.3.2). 이 서브클래스가
비스트리밍(_create_chat_result)과 스트리밍(_convert_chunk_to_generation_chunk) 양쪽에서 raw
reasoning_content를 `message.additional_kwargs["reasoning_content"]`로 실어, 사고 과정 표시(스펙 410
P2/P3)가 소비할 수 있게 한다.

실측(스펙 410): MLX 서버(rapid-mlx)는 **비스트리밍에서만** reasoning_content를 준다(스트리밍 시 사고
블록을 서버가 잘라냄). 스트리밍 훅은 포워드 호환(사고를 델타로 주는 서버가 붙으면 무변경 동작).
추출은 side channel — 본문(content) 결과는 base가 온전히 만들고, 여기선 additional_kwargs만 덧댄다
(사고 없는 모델·응답엔 무영향). .get() 체인만 써 추출 실패가 본문을 깨지 않는다(bare except 불필요).
"""

from __future__ import annotations

from typing import Any

from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

# 서버·버전마다 사고 필드명이 갈린다(스펙 410 연구): vLLM 구버전·SGLang·rapid-mlx=`reasoning_content`,
# vLLM 최신=`reasoning`, Ollama=`thinking`. 어느 이름으로 와도 읽도록 관대하게(포팅 대비).
_REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")


def _reasoning_of(message_dict: object) -> str | None:
    """응답 message/delta dict에서 사고 텍스트(비어있지 않은 문자열)를 뽑는다 — 여러 필드명 허용."""
    if not isinstance(message_dict, dict):
        return None
    for field in _REASONING_FIELDS:
        rc = message_dict.get(field)
        if isinstance(rc, str) and rc:
            return rc
    return None


class ReasoningChatOpenAI(ChatOpenAI):
    """base가 버리는 reasoning_content를 additional_kwargs로 되살리는 provider 서브클래스."""

    def _create_chat_result(
        self, response: dict | Any, generation_info: dict | None = None
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        # structured output 보호(codex 410 P2): base와 **동일한 exclude**로 dump한다 — message.parsed는
        # 임의 Pydantic 객체라 base가 명시 제외 후 별도 복원하므로, 우리도 그 보호를 재현해야 한다.
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(exclude={"choices": {"__all__": {"message": {"parsed"}}}})
        )
        choices = response_dict.get("choices") or []
        for gen, res in zip(result.generations, choices, strict=False):
            rc = _reasoning_of(res.get("message") if isinstance(res, dict) else None)
            if rc:
                gen.message.additional_kwargs["reasoning_content"] = rc
        return result

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ) -> ChatGenerationChunk | None:
        gen = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen is None:
            return None
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
        if choices and isinstance(choices[0], dict):
            rc = _reasoning_of(choices[0].get("delta"))
            if rc:
                gen.message.additional_kwargs["reasoning_content"] = rc
        return gen
