from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from .base import RendererError, setting


DEFAULT_VOICE = "Chinese (Mandarin)_Gentle_Youth"


class MiniMaxTTS:
    """Synchronous MiniMax HTTP TTS; caches by voice/model/text, never by credentials."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.api_key = setting(settings, "minimax_api_key", "")
        self.base_url = setting(settings, "minimax_base_url", "https://api.minimaxi.com").rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.voice_id = setting(settings, "minimax_voice_id", "")
        self.voice_name = setting(settings, "minimax_voice_name", "温润青年")
        self.model = setting(settings, "minimax_model", "speech-02-turbo")
        self.speed = float(setting(settings, "tts_speed", 1.0))
        self.client = client

    def _post(self, endpoint: str, data: dict) -> dict:
        if not self.api_key:
            raise RendererError("MINIMAX_API_KEY is required when TTS is enabled.")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            if self.client:
                response = self.client.post(self.base_url + endpoint, headers=headers, json=data)
            else:
                with httpx.Client(timeout=180) as client:
                    response = client.post(self.base_url + endpoint, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Provider response bodies may echo request contents. Keep credentials and narration out of errors.
            raise RendererError(
                f"MiniMax request failed ({type(exc).__name__}); check endpoint, account and credentials."
            ) from None
        if result.get("base_resp", {}).get("status_code", -1) != 0:
            code = result.get("base_resp", {}).get("status_code", "missing")
            raise RendererError(f"MiniMax returned provider error code {code}.")
        return result

    def resolve_voice(self) -> str:
        if self.voice_id:
            return self.voice_id
        if self.voice_name == "温润青年":
            self.voice_id = DEFAULT_VOICE  # Official MiniMax-AI voice catalog, not an inferred alias.
            return self.voice_id
        result = self._post("/v1/get_voice", {"voice_type": "system"})
        for voice in result.get("system_voice", []):
            if voice.get("voice_name") == self.voice_name:
                self.voice_id = voice["voice_id"]
                return self.voice_id
        raise RendererError("Requested MiniMax voice name was not found; set MINIMAX_VOICE_ID explicitly.")

    def synthesize(self, text: str, output: Path) -> Path:
        if not text.strip() or len(text) >= 10000:
            raise RendererError("Narration must contain 1 to 9999 characters per scene.")
        voice = self.resolve_voice()
        fingerprint = hashlib.sha256(
            json.dumps([text, self.model, voice, self.speed], ensure_ascii=False).encode()
        ).hexdigest()
        cache_key = output.with_suffix(".sha256")
        if (
            output.is_file()
            and output.stat().st_size > 32
            and cache_key.is_file()
            and cache_key.read_text() == fingerprint
        ):
            return output
        result = self._post(
            "/v1/t2a_v2",
            {
                "model": self.model,
                "text": text,
                "stream": False,
                "output_format": "hex",
                "language_boost": "Chinese",
                "voice_setting": {"voice_id": voice, "speed": self.speed, "vol": 1, "pitch": 0},
                "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            },
        )
        try:
            audio = bytes.fromhex(result["data"]["audio"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RendererError("MiniMax response did not contain valid hexadecimal audio.") from exc
        if len(audio) < 32:
            raise RendererError("MiniMax returned empty audio.")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".partial.mp3")
        temporary.write_bytes(audio)
        temporary.replace(output)
        cache_key.write_text(fingerprint)
        return output
