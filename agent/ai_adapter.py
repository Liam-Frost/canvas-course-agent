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
    # auto | codex-oauth | openai-api
    provider: str
    model: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    def complete(self, prompt: str) -> str:
        p = (self.provider or "auto").strip().lower()

        if p == "auto":
            # OpenClaw-like preference: use explicit API key first, then oauth-backed codex cli.
            if self.openai_api_key:
                try:
                    return self._complete_openai_api(prompt)
                except Exception:
                    # fallback to codex oauth path
                    return self._complete_codex_oauth(prompt)
            return self._complete_codex_oauth(prompt)

        if p == "codex-oauth":
            return self._complete_codex_oauth(prompt)
        if p == "openai-api":
            return self._complete_openai_api(prompt)
        raise AIAdapterError(f"Unsupported provider: {self.provider}")

    def doctor(self) -> list[str]:
        p = (self.provider or "auto").strip().lower()
        notes: list[str] = []

        if p in ("auto", "codex-oauth"):
            codex_bin = shutil.which("codex")
            if codex_bin:
                notes.append(f"codex cli: found ({codex_bin})")
            else:
                notes.append("codex cli: missing")

        if p in ("auto", "openai-api"):
            notes.append(f"OPENAI_API_KEY: {'set' if bool(self.openai_api_key) else 'missing'}")
            notes.append(f"OPENAI_BASE_URL: {self.openai_base_url}")

        if p in ("auto", "codex-oauth"):
            notes.append("If codex oauth fails, run: `codex login` (or `openclaw models auth login --provider openai-codex`).")

        return notes

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
            if "401" in msg or "Unauthorized" in msg or "Missing bearer" in msg:
                raise AIAdapterError(
                    "codex oauth/auth invalid. Run `codex login` "
                    "(or `openclaw models auth login --provider openai-codex`) and retry."
                )
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

        with httpx.Client(timeout=45.0) as c:
            # Primary: Responses API
            responses_url = self.openai_base_url.rstrip("/") + "/responses"
            r = c.post(
                responses_url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": prompt, "max_output_tokens": 500},
            )

            if r.status_code < 400:
                data = r.json()
                text = data.get("output_text")
                if isinstance(text, str) and text.strip():
                    return text.strip()

                out_parts: list[str] = []
                for item in data.get("output", []) or []:
                    for content in item.get("content", []) or []:
                        if content.get("type") == "output_text" and content.get("text"):
                            out_parts.append(str(content["text"]))
                if out_parts:
                    return "\n".join(out_parts).strip()

            # Fallback: chat.completions (better compatibility with non-responses setups)
            chat_url = self.openai_base_url.rstrip("/") + "/chat/completions"
            r2 = c.post(
                chat_url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )

        if r2.status_code >= 400:
            err1 = f"responses={r.status_code}"
            err2 = f"chat={r2.status_code}"
            raise AIAdapterError(f"openai api failed ({err1}, {err2}): {r2.text[:300]}")

        data2 = r2.json()
        try:
            content = data2["choices"][0]["message"]["content"]
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception:
            pass

        raise AIAdapterError("openai api returned no output text: " + json.dumps(data2)[:500])
