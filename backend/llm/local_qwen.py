"""Resident, serialized local inference, warmed before the API accepts requests."""

from threading import Lock
from typing import Any

from api.settings import setting
from config import load_config


CONFIG = load_config("llm")


_lock = Lock()
_processor: Any = None
_model: Any = None
_model_id: str | None = None
_warmed_up = False


def _load_model(model_id: str) -> None:
    """Called with _lock held, including during startup."""
    global _processor, _model, _model_id

    import torch
    from transformers import AutoProcessor, AutoModelForMultimodalLM, BitsAndBytesConfig

    if str(CONFIG["device_map"]).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required by llm/config.yaml but is unavailable")

    if _model is None:
        options = {"device_map": CONFIG["device_map"], "dtype": CONFIG["dtype"]}
        if quantization := CONFIG.get("quantization"):
            options["quantization_config"] = BitsAndBytesConfig(
                **quantization, bnb_4bit_compute_dtype=getattr(torch, CONFIG["dtype"]),
            )
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModelForMultimodalLM.from_pretrained(model_id, **options)
        model.eval()
        _processor, _model, _model_id = processor, model, model_id
    elif _model_id != model_id:
        raise RuntimeError("Restart the backend after changing the local LLM model")


def _generate(prompt: str, model_id: str, *, warming: bool = False) -> str:
    import torch

    _load_model(model_id)
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
    generation = {**CONFIG["generation"], "max_new_tokens": int(setting(
        "LOCAL_LLM_MAX_NEW_TOKENS", str(CONFIG["generation"]["max_new_tokens"]),
    ))}
    if warming:
        # Two tokens exercise both prefill and cached autoregressive decoding.
        generation = {"max_new_tokens": 2, "min_new_tokens": 2, "do_sample": False}
    with torch.inference_mode():
        outputs = _model.generate(**inputs, **generation)
    return _processor.decode(
        outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True,
    ).strip()


def warmup(model_id: str) -> None:
    global _warmed_up
    with _lock:
        if _warmed_up and _model_id == model_id:
            return
        _generate("こんにちは", model_id, warming=True)
        import torch

        if str(_model.device).startswith("cuda"):
            torch.cuda.synchronize(_model.device)
        _warmed_up = True


def generate(prompt: str, model_id: str) -> str:
    # Startup and requests share the same model and lock across event loops.
    with _lock:
        return _generate(prompt, model_id)


def is_ready(model_id: str) -> bool:
    return _warmed_up and _model_id == model_id
