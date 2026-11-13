"""Lazy, serialized local inference so API requests do not block the event loop."""

from threading import Lock
from typing import Any

from api.settings import setting
from config import load_config


CONFIG = load_config("llm")


_lock = Lock()
_processor: Any = None
_model: Any = None
_model_id: str | None = None


def generate(prompt: str, model_id: str) -> str:
    global _processor, _model, _model_id

    # Keep loading and generation under the same lock, including across event loops.
    with _lock:
        import torch
        from transformers import AutoProcessor, AutoModelForMultimodalLM

        if str(CONFIG["device_map"]).startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA is required by llm/config.yaml but is unavailable")

        if _model is None:
            processor = AutoProcessor.from_pretrained(model_id)
            model = AutoModelForMultimodalLM.from_pretrained(
                model_id, device_map=CONFIG["device_map"], dtype=CONFIG["dtype"],
            )
            model.eval()
            _processor, _model, _model_id = processor, model, model_id
        elif _model_id != model_id:
            raise RuntimeError("Restart the backend after changing the local LLM model")

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        inputs = _processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=CONFIG["enable_thinking"],
        ).to(_model.device)
        if inputs["input_ids"].shape[-1] > CONFIG["max_input_tokens"]:
            raise ValueError("Prompt exceeds max_input_tokens in llm/config.yaml")
        with torch.inference_mode():
            outputs = _model.generate(
                **inputs,
                **{**CONFIG["generation"], "max_new_tokens": int(setting(
                    "LOCAL_LLM_MAX_NEW_TOKENS", str(CONFIG["generation"]["max_new_tokens"]),
                ))},
            )
        return _processor.decode(
            outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True,
        ).strip()
