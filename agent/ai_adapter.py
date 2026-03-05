from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

import httpx


class AIAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIAdapter:
    provider: str  # codex-oauth | openai-api
    model: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    def complete(self, prompt: str) -> str:
        p = (self.provider or "").strip().lower()
        if p == "codex-oauth":
            return self._complete_codex_oauth(prompt)
        if p == "openai-api":
            return self._complete_openai_api(prompt)
        raise AIAdapterError(f"Unsupported provider: {self.provider}")

    def _complete_codex_oauth(self, prompt: str) -> str:
        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise AIAdapterError("`codex` CLI not found in PATH")

        cmd = [codex_bin, "exec"]
        if self.model:
            cmd += ["--model", self.model]
        cmd += [prompt]

        try:
            cp = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired as e:
            raise AIAdapterError(f"codex exec timeout: {e}") from e

        if cp.returncode != 0:
            msg = (cp.stderr or cp.stdout or "").strip()
            raise AIAdapterError(f"codex exec failed ({cp.returncode}): {msg}")

        out = (cp.stdout or "").strip()
        if not out:
            raise AIAdapterError("codex exec returned empty output")
        return out

    def _complete_openai_api(self, prompt: str) -> str:
        key = self.openai_api_key or ""
        if not key:
            raise AIAdapterError("OPENAI_API_KEY is not set")

        model = self.model or "gpt-4.1-mini"
        url = self.openai_base_url.rstrip("/") + "/responses"

        payload = {
            "model": model,
            "input": prompt,
            "max_output_tokens": 500,
        }

        with httpx.Client(timeout=45.0) as c:
            r = c.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if r.status_code >= 400:
            raise AIAdapterError(f"openai api failed: HTTP {r.status_code} {r.text[:300]}")

        data = r.json()

        # Prefer SDK-compatible key if present
        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        # Fallback parser
        out_parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text" and content.get("text"):
                    out_parts.append(str(content["text"]))

        if out_parts:
            return "\n".join(out_parts).strip()

        raise AIAdapterError("openai api returned no output text: " + json.dumps(data)[:500])
