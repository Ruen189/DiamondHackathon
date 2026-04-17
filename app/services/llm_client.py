import os
import time
from typing import Any

import requests
from app.env import load_env


load_env()
LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://localhost:8080/v1/chat/completions")
WHISPER_SERVER_URL = os.getenv("WHISPER_SERVER_URL", "http://localhost:8081/inference")
TEXT_MODEL = os.getenv("TEXT_MODEL", "qwen-3.5-4b-q5_k_m.gguf")
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", "200000"))


def generate_completion(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
    started = time.time()
    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 1200,
        "extra_body": {"n_ctx": CONTEXT_WINDOW},
    }
    response = requests.post(LLAMA_SERVER_URL, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    elapsed_ms = int((time.time() - started) * 1000)
    tokens_out = int(data.get("usage", {}).get("completion_tokens", 0))
    tokens_per_sec = round(tokens_out / max(elapsed_ms / 1000, 1e-3), 2) if tokens_out else 0.0
    text = data["choices"][0]["message"]["content"]
    return {
        "text": text,
        "elapsed_ms": elapsed_ms,
        "tokens_out": tokens_out,
        "tokens_per_sec": tokens_per_sec,
    }


def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    files = {"file": (filename, file_bytes, "audio/wav")}
    response = requests.post(WHISPER_SERVER_URL, files=files, timeout=240)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data.get("text", "").strip()
    return str(data)
