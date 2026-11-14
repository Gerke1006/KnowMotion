from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx

from .base import RendererError, setting


DEFAULT_VOICE = "Chinese (Mandarin)_Gentle_Youth"
ALIGNMENT_SCHEMA_VERSION = "2.0"
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def _pronunciation_span(word: dict) -> tuple[int, int] | None:
    """Provider pronunciation offsets disambiguate several sounds of one token."""
    keys = {"pronounce_word", "pronounce_word_begin", "pronounce_word_end"}
    if not keys.intersection(word):
        return None
    start, end, text = (word.get("pronounce_word_begin"), word.get("pronounce_word_end"),
                        word.get("pronounce_word"))
    if (type(start) is not int or type(end) is not int or not 0 <= start < end
            or not isinstance(text, str) or len(text) != end - start):
        raise RendererError("MiniMax returned invalid pronunciation offsets.")
    return start, end


def normalize_minimax_words(text: str, subtitles: object) -> list[dict]:
    """Keep provider word boundaries; never invent timing by splitting a sentence.

    MiniMax's word offsets are Unicode character offsets in the complete input,
    and its time_begin/time_end are milliseconds in the untrimmed audio.
    https://platform.minimax.cn/docs/api-reference/speech-t2a-http
    """
    if isinstance(subtitles, dict):
        subtitles = subtitles.get("subtitles", subtitles.get("subtitle"))
    if not isinstance(subtitles, list) or not subtitles:
        raise RendererError("MiniMax did not return a subtitle segment array.")
    words, previous_end, previous_time, previous_pronunciation = [], 0, 0.0, None
    for segment in subtitles:
        observed = segment.get("timestamped_words") if isinstance(segment, dict) else None
        if not isinstance(observed, list) or not observed:
            raise RendererError("MiniMax word timestamps are unavailable; sentence timing is not word alignment.")
        for word in observed:
            try:
                start_index, end_index = word["word_begin"], word["word_end"]
                begin, end = float(word["time_begin"]) / 1000, float(word["time_end"]) / 1000
                provider_text = word["word"]
            except (KeyError, TypeError, ValueError):
                raise RendererError("MiniMax returned malformed word timestamps.") from None
            # MiniMax can emit a measured whitespace token between Latin math
            # terms (for example the space in "sin x"). It is part of the
            # original text and has genuine timing, so preserve it unchanged.
            if (type(start_index) is not int or type(end_index) is not int
                    or not 0 <= start_index < end_index <= len(text)
                    or not isinstance(provider_text, str) or not provider_text
                    or provider_text != text[start_index:end_index]):
                raise RendererError("MiniMax word text or character offsets do not match the original narration.")
            if (not math.isfinite(begin) or not math.isfinite(end)
                    or begin < previous_time - .001 or end <= begin):
                raise RendererError("MiniMax word timestamps are invalid or non-monotonic.")
            pronunciation = _pronunciation_span(word)
            if start_index < previous_end:
                # Numbers and abbreviations can expand to several pronounced
                # syllables. MiniMax repeats the exact original word span for
                # each syllable and advances pronounce_word offsets. Preserve
                # the observed outer boundaries as one original-text token.
                # Partial overlaps, replayed spans, and guessed splits fail.
                previous = words[-1] if words else None
                if (not previous or previous["char_start"] != start_index
                        or previous["char_end"] != end_index or pronunciation is None
                        or previous_pronunciation is None
                        or pronunciation[0] != previous_pronunciation[1]):
                    raise RendererError("MiniMax word spans overlap without consecutive pronunciation evidence.")
                previous["end"] = end
            else:
                words.append({"text": text[start_index:end_index], "char_start": start_index,
                              "char_end": end_index, "start": begin, "end": end})
            previous_end, previous_time = end_index, end
            previous_pronunciation = pronunciation
    covered = {i for word in words for i in range(word["char_start"], word["char_end"])}
    if any(char.isalnum() and i not in covered for i, char in enumerate(text)):
        raise RendererError("MiniMax word timestamps do not cover the spoken text; alignment cannot be estimated.")
    return words


def _atomic_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
        for attempt in range(3):
            try:
                if self.client:
                    response = self.client.post(self.base_url + endpoint, headers=headers, json=data)
                else:
                    with httpx.Client(timeout=180) as client:
                        response = client.post(self.base_url + endpoint, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                transient = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))
                transient |= isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in TRANSIENT_HTTP_STATUS
                if transient and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                # Provider bodies and transport URLs can echo credentials.
                raise RendererError(f"MiniMax request failed ({type(exc).__name__}); "
                                    "check endpoint, account and credentials.") from None
            if not isinstance(result, dict) or not isinstance(result.get("base_resp"), dict):
                raise RendererError("MiniMax returned an invalid response envelope.")
            code = result["base_resp"].get("status_code", "missing")
            if type(code) is int and code == 0:
                return result
            if type(code) is int and code in {1001, 1002, 1039} and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            # Status is normally numeric. Do not echo arbitrary provider strings.
            code = code if type(code) is int else "invalid"
            raise RendererError(f"MiniMax returned provider error code {code}.")
        raise RendererError("MiniMax transient request retry budget exhausted.")

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

    def _subtitle_json(self, url: str) -> object:
        # Download URLs are provider-generated. Never send the API credential to
        # the object store, follow redirects, or accept a local/file URL.
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise RendererError("MiniMax returned an invalid subtitle download URL.") from None
        allowed = ("minimaxi.com", "minimax.io", "minimax.cn", "minimax.chat",
                   "myqcloud.com", "aliyuncs.com")
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or port not in (None, 443)
                or not any(host == suffix or host.endswith("." + suffix) for suffix in allowed)):
            raise RendererError("MiniMax returned an unsupported subtitle download host.")
        for attempt in range(3):
            try:
                # build_request normally inherits client headers; remove auth even
                # when an injected/shared client has a default Authorization header.
                if self.client:
                    request = self.client.build_request("GET", url)
                    request.headers.pop("Authorization", None)
                    response = self.client.send(request, auth=None, follow_redirects=False)
                else:
                    with httpx.Client(timeout=60, follow_redirects=False) as client:
                        response = client.get(url)
                response.raise_for_status()
                if len(response.content) > 4_000_000:
                    raise RendererError("MiniMax subtitle file exceeds the supported size.")
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                transient = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))
                transient |= isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in TRANSIENT_HTTP_STATUS
                if transient and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RendererError(f"MiniMax subtitle download failed ({type(exc).__name__}); "
                                    "the synthesized audio is cached for recovery.") from None
        raise RendererError("MiniMax subtitle download retry budget exhausted.")

    def synthesize_aligned(self, text: str, output: Path) -> dict:
        """Synthesize once with genuine word timestamps; resume a failed download.

        Cached audio and raw provider JSON are paired by SHA-256. A pending signed
        download URL exists only in the local recovery sidecar and is removed as
        soon as the raw JSON is saved; it is never returned in reports or errors.
        """
        if not text.strip() or len(text) >= 10000:
            raise RendererError("Narration must contain 1 to 9999 characters per scene.")
        output = Path(output)
        voice = self.resolve_voice()
        fingerprint = hashlib.sha256(json.dumps(
            ["minimax-word-v2", self.base_url, text, self.model, voice, self.speed],
            ensure_ascii=False).encode()).hexdigest()
        state_path = output.with_suffix(".alignment-state.json")
        raw_path = output.with_suffix(".alignment.raw.json")
        alignment_path = output.with_suffix(".alignment.json")
        state = {}
        if state_path.is_file() and output.is_file():
            try:
                saved = json.loads(state_path.read_text(encoding="utf-8"))
                if (saved.get("fingerprint") == fingerprint
                        and saved.get("audio_sha256") == hashlib.sha256(output.read_bytes()).hexdigest()):
                    state = saved
            except (ValueError, OSError):
                pass
        if not state:
            result = self._post("/v1/t2a_v2", {
                "model": self.model, "text": text, "stream": False, "output_format": "hex",
                "language_boost": "Chinese", "subtitle_enable": True, "subtitle_type": "word",
                "voice_setting": {"voice_id": voice, "speed": self.speed, "vol": 1, "pitch": 0},
                "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            })
            try:
                audio = bytes.fromhex(result["data"]["audio"])
            except (KeyError, TypeError, ValueError):
                raise RendererError("MiniMax response did not contain valid hexadecimal audio.") from None
            if len(audio) < 32:
                raise RendererError("MiniMax returned empty audio.")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".partial.mp3")
            temporary.write_bytes(audio)
            temporary.replace(output)
            state = {"fingerprint": fingerprint, "audio_sha256": hashlib.sha256(audio).hexdigest(),
                     "provider": "minimax", "trace_id": str(result.get("trace_id", "")),
                     "pending_subtitle_url": result["data"].get("subtitle_file"),
                     "raw_sha256": None}
            _atomic_json(state_path, state)
        raw = None
        if raw_path.is_file() and state.get("raw_sha256"):
            data = raw_path.read_bytes()
            if hashlib.sha256(data).hexdigest() == state["raw_sha256"]:
                try:
                    raw = json.loads(data)
                except ValueError:
                    pass
        if raw is None:
            url = state.get("pending_subtitle_url")
            if not isinstance(url, str) or not url:
                raise RendererError("MiniMax did not provide recoverable word subtitles; cached audio was retained.")
            raw = self._subtitle_json(url)
            _atomic_json(raw_path, raw)
            state["raw_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            state.pop("pending_subtitle_url", None)
            _atomic_json(state_path, state)
        words = normalize_minimax_words(text, raw)
        alignment = {"schema_version": ALIGNMENT_SCHEMA_VERSION, "provider": "minimax", "granularity": "word",
                     "normalization": "consecutive-pronunciation-fragments-share-original-word-span",
                     "timebase": "untrimmed-provider-audio-seconds", "text": text, "words": words,
                     "trace_id": state["trace_id"], "audio_sha256": state["audio_sha256"],
                     "raw_sha256": state["raw_sha256"], "raw_path": raw_path.name}
        _atomic_json(alignment_path, alignment)
        return {"audio_path": output, "alignment_path": alignment_path, "words": words,
                "provider": "minimax", "trace_id": state["trace_id"]}
