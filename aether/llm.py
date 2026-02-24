from __future__ import annotations
import json
import re
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


def extract_json(raw: str) -> dict:
    """
    Robustly extract the first JSON object from raw LLM output.
    Handles markdown fences, leading prose, trailing text, and empty responses.
    Raises json.JSONDecodeError if no valid JSON object is found.
    """
    if not raw or not raw.strip():
        raise json.JSONDecodeError("Empty response from LLM", "", 0)

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r"```(?:json)?\s*", "", raw)
    text = re.sub(r"```", "", text).strip()

    # Try parsing the whole cleaned string first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back: find first balanced {...} block
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise json.JSONDecodeError("No valid JSON object found in LLM response", raw, 0)


async def ping() -> bool:
    """Return True if LM Studio is reachable and has a model loaded."""
    try:
        models = await _client.models.list()
        return len(models.data) > 0
    except Exception as exc:
        print(f"[llm] ping failed: {exc}")
        return False
