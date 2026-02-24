from __future__ import annotations
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from .config import LM_STUDIO_BASE_URL, LM_STUDIO_API_KEY, LLM_MODEL

_client = AsyncOpenAI(
    base_url=LM_STUDIO_BASE_URL,
    api_key=LM_STUDIO_API_KEY,
)


async def llm_complete(prompt: str, system: Optional[str] = None) -> str:
    """Single-turn completion. Returns the assistant's text."""
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = await _client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content


async def llm_tool_call(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Any:
    """Tool-calling completion. Returns the raw message object."""
    response = await _client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    return response.choices[0].message


async def ping() -> bool:
    """Return True if LM Studio is reachable and has a model loaded."""
    try:
        models = await _client.models.list()
        return len(models.data) > 0
    except Exception as exc:
        print(f"[llm] ping failed: {exc}")
        return False
