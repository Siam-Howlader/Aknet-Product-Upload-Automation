import json
from typing import Protocol

import httpx


class AIProvider(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...

class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        temperature: float = 0.3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key or not self.model:
            raise RuntimeError("AI_API_KEY and AI_MODEL must be configured")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "product_content",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                        },
                        "required": ["description"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
            "temperature": self.temperature,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("description"), str
        ):
            raise ValueError(
                "AI response must contain a string description")
        return parsed["description"].strip()


class OllamaProvider:
    """Local Ollama provider; it does not require an API key or paid account."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 600.0,
        temperature: float = 0.3,
        num_ctx: int = 8192,
        num_predict: int = 512,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.model:
            raise RuntimeError("AI_MODEL must name an installed Ollama model")

        payload = {
            "model": self.model,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Ollama did not respond within {self.timeout_seconds:g} "
                "seconds. Increase OLLAMA_TIMEOUT_SECONDS or use a "
                "smaller/faster model."
            ) from exc
        response.raise_for_status()
        body = response.json()
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned an empty description")
        if body.get("done_reason") == "length":
            raise RuntimeError(
                "Ollama reached OLLAMA_NUM_PREDICT before finishing its "
                "description. Reduce prompt size or increase "
                "OLLAMA_NUM_PREDICT."
            )
        return content.strip()
