import asyncio
import json
from typing import Any

from api.settings import setting
from config import load_config


CONFIG = load_config("llm")


def configured() -> bool:
    return bool(model())


def model() -> str:
    return setting("LOCAL_LLM_MODEL", CONFIG["model"])


async def complete(prompt: str, *, json_schema: dict[str, Any] | None = None) -> str:
    if not configured():
        raise RuntimeError("Local LLM settings are incomplete")
    from llm.local_qwen import generate

    if json_schema:
        prompt += "\n\n出力は次の JSON Schema に沿う JSON object だけにしてください。余分な説明や Markdown は付けないでください。\n"
        prompt += json.dumps(json_schema, ensure_ascii=False)
    return await asyncio.to_thread(generate, prompt, model())


async def complete_json(prompt: str, schema: dict[str, Any]) -> dict:
    raw = await complete(prompt, json_schema=schema)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"LLM returned invalid JSON: {raw[:400]}") from error
    if not isinstance(value, dict):
        raise RuntimeError("LLM JSON response must be an object")
    return value


def status() -> dict[str, Any]:
    return {
        "configured": configured(),
        "provider": "local",
        "textModel": model(),
    }
