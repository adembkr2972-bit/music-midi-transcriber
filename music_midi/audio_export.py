from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any


DEFAULT_SOUNDFONT_NAME = "GeneralUser GS 1.471.sf2"
DEFAULT_SOUNDFONT_URL = (
    "https://raw.githubusercontent.com/planet-s/generaluser-gs/"
    "231d3a3854ba1d73ec3dd0b1e377a627a8d3a115/generaluser-gs.sf2"
)
DEFAULT_SOUNDFONT_SIZE = 31_281_186
DEFAULT_SOUNDFONT_SHA256 = "f45b6b4a68b6bf3d792fcbb6d7de24dc701a0f89c5900a21ef3aaece993b839a"
SOUNDFONT_CACHE_LOCK = threading.Lock()


def _soundfont_cache_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    cache_root = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return cache_root / "MusicMidiTranscriber" / "soundfonts" / DEFAULT_SOUNDFONT_NAME


def _is_valid_default_soundfont(data: bytes) -> bool:
    return (
        len(data) == DEFAULT_SOUNDFONT_SIZE
        and hashlib.sha256(data).hexdigest() == DEFAULT_SOUNDFONT_SHA256
    )


def get_default_soundfont_bytes() -> bytes:
    """Load the cached default SoundFont, downloading it once if needed."""
    cache_path = _soundfont_cache_path()
    with SOUNDFONT_CACHE_LOCK:
        try:
            cached = cache_path.read_bytes()
        except OSError:
            cached = b""
        if _is_valid_default_soundfont(cached):
            return cached

        request = urllib.request.Request(
            DEFAULT_SOUNDFONT_URL,
            headers={"User-Agent": "Music-MIDI-Transcriber"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            soundfont_bytes = response.read(DEFAULT_SOUNDFONT_SIZE + 1)
        if not _is_valid_default_soundfont(soundfont_bytes):
            raise RuntimeError(
                "The default SoundFont download was incomplete or invalid. "
                "Upload a valid .sf2 SoundFont and try again."
            )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="soundfont_",
            suffix=".tmp",
            dir=cache_path.parent,
            delete=False,
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            temp_file.write(soundfont_bytes)
        temporary_path.replace(cache_path)
        return soundfont_bytes


def split_midi_tracks(midi_bytes: bytes, combined_filename: str) -> list[dict[str, Any]]:
    """Write each instrument from a multi-track MIDI file as its own MIDI file."""
    import pretty_midi

    combined_stem = Path(combined_filename).stem
    if combined_stem.endswith("_techno"):
        combined_stem = combined_stem[: -len("_techno")]
    song_slug = _safe_slug(combined_stem) or "song"

    exports: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="music_midi_export_") as directory:
        temp_dir = Path(directory)
        source_path = temp_dir / "combined.mid"
        source_path.write_bytes(midi_bytes)
        source = pretty_midi.PrettyMIDI(str(source_path))
        _, tempi = source.get_tempo_changes()
        initial_tempo = float(tempi[0]) if len(tempi) else 120.0

        for index, instrument in enumerate(source.instruments, start=1):
            track_name = instrument.name or f"Track {index}"
            single_track = pretty_midi.PrettyMIDI(initial_tempo=initial_tempo)
            single_track.instruments.append(instrument)
            filename = f"{song_slug}_{_safe_slug(track_name) or f'track_{index}'}.mid"
            output_path = temp_dir / filename
            single_track.write(str(output_path))
            exports.append(
                {
                    "name": track_name,
                    "filename": filename,
                    "midi": output_path.read_bytes(),
                    "program": int(instrument.program),
                    "is_drum": bool(instrument.is_drum),
                    "note_count": len(instrument.notes),
                }
            )
    return exports


def build_export_zip(exports: list[dict[str, Any]], content_key: str) -> bytes:
    archive_bytes = BytesIO()
    compression = (
        zipfile.ZIP_STORED if content_key == "mp3" else zipfile.ZIP_DEFLATED
    )
    with zipfile.ZipFile(archive_bytes, mode="w", compression=compression) as archive:
        for export in exports:
            filename = Path(export["filename"]).with_suffix(
                ".mp3" if content_key == "mp3" else ".mid"
            )
            archive.writestr(str(filename), export[content_key])
    return archive_bytes.getvalue()


def render_track_to_mp3(midi_bytes: bytes, soundfont_bytes: bytes) -> bytes:
    """Render one MIDI lane and peak-normalize its stereo 320 kbps MP3 preview."""
    import lameenc
    import numpy as np
    import pretty_midi
    import tinysoundfont

    sample_rate = 48_000
    tail_seconds = 2.0
    with tempfile.TemporaryDirectory(prefix="music_midi_render_") as directory:
        midi_path = Path(directory) / "track.mid"
        midi_path.write_bytes(midi_bytes)
        midi = pretty_midi.PrettyMIDI(str(midi_path))

    if len(midi.instruments) != 1:
        raise ValueError("Each MP3 export must contain exactly one MIDI track.")
    instrument = midi.instruments[0]
    if not instrument.notes:
        raise ValueError("This MIDI track has no notes to render.")

    synth = tinysoundfont.Synth(gain=-8.0, samplerate=sample_rate)
    soundfont_id = synth.sfload(soundfont_bytes)
    channel = 9 if instrument.is_drum else 0
    synth.program_select(
        channel,
        soundfont_id,
        0,
        int(instrument.program),
        is_drums=bool(instrument.is_drum),
    )

    events: list[tuple[int, int, int, int]] = []
    for note in instrument.notes:
        start_frame = max(0, round(note.start * sample_rate))
        end_frame = max(start_frame + 1, round(note.end * sample_rate))
        events.append((start_frame, 1, int(note.pitch), int(note.velocity)))
        events.append((end_frame, 0, int(note.pitch), 0))
    events.sort(key=lambda event: (event[0], event[1], event[2]))

    pcm_spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    current_frame = 0
    peak = 0.0

    def render_until(target_frame: int) -> None:
        nonlocal current_frame, peak
        while current_frame < target_frame:
            frame_count = min(8192, target_frame - current_frame)
            audio_buffer = synth.generate_simple(frame_count)
            audio = np.frombuffer(audio_buffer, dtype=np.float32)
            peak = max(peak, float(np.max(np.abs(audio))))
            pcm_spool.write(audio_buffer)
            current_frame += frame_count

    for frame, event_type, pitch, velocity in events:
        render_until(frame)
        if event_type == 0:
            synth.noteoff(channel, pitch)
        else:
            synth.noteon(channel, pitch, velocity)

    final_frame = events[-1][0] + round(tail_seconds * sample_rate)
    render_until(final_frame)

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(320)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(2)
    encoder.set_quality(2)

    target_peak = 10 ** (-1.0 / 20.0)
    gain = target_peak / peak if peak > 0 else 1.0
    mp3_bytes = bytearray()
    pcm_spool.seek(0)
    while pcm_chunk := pcm_spool.read(8192 * 2 * 4):
        audio = np.frombuffer(pcm_chunk, dtype=np.float32)
        pcm = np.clip(audio * gain, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2", copy=False)
        encoded = encoder.encode(pcm.tobytes())
        if encoded:
            mp3_bytes.extend(encoded)
    mp3_bytes.extend(encoder.flush())
    pcm_spool.close()
    return bytes(mp3_bytes)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_-").lower()
