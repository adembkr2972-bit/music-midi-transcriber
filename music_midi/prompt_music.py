"""Prompt-based audio generation through fal.ai's ACE-Step endpoint."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


MODEL_ID = "fal-ai/ace-step/prompt-to-audio"
PRICE_PER_SECOND_USD = 0.0002
MAX_AUDIO_BYTES = 200 * 1024 * 1024


class MusicGenerationError(RuntimeError):
    """A safe, user-facing error from the prompt-to-audio service."""


def _fal_request(
    url: str,
    *,
    api_key: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 30,
) -> dict:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Key {api_key}",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            response_data = response.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            message = "fal.ai rejected the API key. Check that the key is valid and active."
        elif exc.code == 429:
            message = "fal.ai is rate-limiting requests or the account has insufficient credits."
        else:
            message = f"fal.ai returned an HTTP {exc.code} response. Please try again later."
        raise MusicGenerationError(message) from None
    except (TimeoutError, URLError):
        raise MusicGenerationError(
            "Could not reach fal.ai. Check your internet connection and try again."
        ) from None

    try:
        return json.loads(response_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MusicGenerationError("fal.ai returned an unreadable response.") from None


def _download_audio(audio_url: str) -> tuple[bytes, str, str]:
    parsed = urlsplit(audio_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise MusicGenerationError("fal.ai returned an invalid audio download link.")

    request = Request(audio_url, headers={"Accept": "audio/wav, application/octet-stream"})
    try:
        with urlopen(request, timeout=60) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_AUDIO_BYTES:
                raise MusicGenerationError("The generated audio is too large to download in this app.")
            audio_bytes = response.read(MAX_AUDIO_BYTES + 1)
            content_type = response.headers.get_content_type() or "audio/wav"
    except MusicGenerationError:
        raise
    except (HTTPError, TimeoutError, URLError):
        raise MusicGenerationError("The track was generated, but its download failed. Try again shortly.") from None

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise MusicGenerationError("The generated audio is too large to download in this app.")
    if not audio_bytes:
        raise MusicGenerationError("fal.ai returned an empty audio file.")

    return audio_bytes, content_type, parsed.path.rsplit("/", 1)[-1]


def generate_prompt_track(
    *,
    api_key: str,
    prompt: str,
    instrumental: bool,
    duration_seconds: int,
    on_status: Callable[[str, float], None] | None = None,
    max_wait_seconds: int = 900,
) -> dict:
    """Submit a track, wait for the queue result, and download its audio."""
    submit_url = f"https://queue.fal.run/{MODEL_ID}"
    submitted = _fal_request(
        submit_url,
        api_key=api_key,
        method="POST",
        payload={
            "prompt": prompt,
            "instrumental": instrumental,
            "duration": float(duration_seconds),
        },
        timeout=45,
    )
    request_id = submitted.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise MusicGenerationError("fal.ai did not return a generation request ID.")

    safe_request_id = quote(request_id, safe="")
    request_url = f"{submit_url}/requests/{safe_request_id}"
    status_url = f"{request_url}/status"
    started_at = time.monotonic()
    while True:
        elapsed = time.monotonic() - started_at
        if elapsed > max_wait_seconds:
            raise MusicGenerationError(
                "Generation did not finish within 15 minutes. The request may still be running; "
                f"request ID: {request_id}. Check fal.ai before submitting it again."
            )

        status_data = _fal_request(status_url, api_key=api_key, timeout=30)
        status = str(status_data.get("status", "")).upper()
        if on_status:
            on_status(status or "IN_PROGRESS", elapsed)

        if status == "COMPLETED":
            result = _fal_request(request_url, api_key=api_key, timeout=45)
            audio = result.get("audio") or {}
            audio_url = audio.get("url") if isinstance(audio, dict) else None
            if not isinstance(audio_url, str):
                raise MusicGenerationError("fal.ai completed the request without returning an audio file.")
            audio_bytes, content_type, remote_name = _download_audio(audio_url)
            filename = Path(str(audio.get("file_name") or remote_name or "luthence_track.wav")).name
            if not filename or filename in {".", ".."}:
                filename = "luthence_track.wav"
            if "." not in filename:
                filename = f"{filename}.wav"
            return {
                "audio_bytes": audio_bytes,
                "content_type": content_type,
                "filename": filename,
                "seed": result.get("seed"),
                "request_id": request_id,
            }

        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            raise MusicGenerationError(
                f"fal.ai could not generate this track (request ID: {request_id}). Please adjust the prompt or retry."
            )

        time.sleep(3)
