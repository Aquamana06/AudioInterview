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
        prompt += "文字列内の改行は\\nにエスケープし、文字列・配列・オブジェクトをすべて閉じてください。\n"
        prompt += json.dumps(json_schema, ensure_ascii=False)
    if json_schema:
        return await asyncio.to_thread(generate, prompt, model(), json_output=True)
    return await asyncio.to_thread(generate, prompt, model())


async def complete_json(prompt: str, schema: dict[str, Any]) -> dict:
    raw = await complete(prompt, json_schema=schema)
    candidate = raw.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        first_line, separator, remainder = candidate.partition("\n")
        if separator and first_line.lower() in ("```", "```json"):
            candidate = remainder[:-3].strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"LLM returned invalid JSON ({error.msg}; line={error.lineno}, column={error.colno}, "
            f"position={error.pos}, output_chars={len(raw)}): {raw[:400]}"
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError("LLM JSON response must be an object")
    return value


def status() -> dict[str, Any]:
    from llm.local_qwen import is_ready

    return {
        "configured": configured(),
        "ready": is_ready(model()),
        "provider": "local",
        "textModel": model(),
    }
