from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from threading import Event
from pathlib import Path
from typing import Callable, Sequence


PARTS = {
    "kick": {
        "stem": "drums.wav",
        "track_name": "Kick",
        "kind": "drum",
        "drum_lane": "kick",
        "recommended_instrument": "Ableton Drum Rack or Simpler",
        "recommended_sound": "A short, punchy hard-techno kick with a clear transient. Tune its low fundamental to the song and keep the sub end controlled.",
    },
    "percussion": {
        "stem": "drums.wav",
        "track_name": "Percussion (snare / clap / hats)",
        "kind": "drum",
        "drum_lane": "percussion",
        "recommended_instrument": "Ableton Drum Rack",
        "recommended_sound": "Load tight snare or clap and closed/open hat samples. The MIDI uses notes 38/39 for snare/clap, 42/46 for closed/open hat, and 45 for tom; map those notes to matching pads.",
    },
    "bass": {
        "stem": "bass.wav",
        "track_name": "Bass / sub",
        "kind": "pitched",
        "line": "low",
        "minimum_frequency": 27.5,
        "maximum_frequency": 330.0,
        "minimum_pitch": 24,
        "maximum_pitch": 65,
        "program": 38,
        "recommended_instrument": "Ableton Operator, Wavetable, or Drift",
        "recommended_sound": "Try a mono rolling saw or square bass with light saturation and a clean sub layer. Keep it tight around the kick; the MIDI also carries a General MIDI Synth Bass 1 program hint.",
    },
    "synths": {
        "stem": "other.wav",
        "track_name": "Synths / lead / chords / FX",
        "kind": "pitched",
        "line": "polyphonic",
        "minimum_frequency": 55.0,
        "maximum_frequency": 1800.0,
        "minimum_pitch": 36,
        "maximum_pitch": 100,
        "program": 80,
        "recommended_instrument": "Ableton Wavetable, Drift, or Operator",
        "recommended_sound": "Try a short pluck or chord stab, or a bright saw/square lead. This source combines leads, chords, pads, and effects, so choose the patch by listening; the MIDI carries a General MIDI square-lead hint.",
    },
    "vocals": {
        "stem": "vocals.wav",
        "track_name": "Vocals",
        "kind": "pitched",
        "line": "high",
        "minimum_frequency": 75.0,
        "maximum_frequency": 1400.0,
        "minimum_pitch": 40,
        "maximum_pitch": 100,
        "program": 53,
        "recommended_instrument": "Ableton Simpler or Sampler, or a choir/voice synth patch",
        "recommended_sound": "Use vocal chops or an 'ah/oh' style patch. These MIDI notes are a pitch guide; they do not include the original vocal audio.",
    },
}

SIMPLIFICATION_MIN_SECONDS = {
    "Light": 0.045,
    "Balanced": 0.07,
    "Strong": 0.12,
}

QUANTIZATION_DIVISIONS = {
    "Off": None,
    "Eighth notes": 2,
    "Sixteenth notes": 4,
    "Thirty-second notes": 8,
}

SEPARATION_MODELS = {
    "Fast (recommended)": "htdemucs",
    "Higher separation, slower": "htdemucs_ft",
    "Highest separation quality (very slow)": "htdemucs_ft",
}

SEPARATION_SHIFTS = {
    "Fast (recommended)": 1,
    "Higher separation, slower": 1,
    "Highest separation quality (very slow)": 10,
}

PITCH_SENSITIVITY = {
    "Balanced (recommended)": (0.5, 0.3),
    "More sensitive (may add extra notes)": (0.35, 0.2),
    "More conservative (may miss quiet notes)": (0.65, 0.4),
}


class TranscriptionCancelled(Exception):
    """Raised when the user stops an active transcription."""


def load_basic_pitch_model():
    """Load the Basic Pitch model once so it can be reused for each stem."""
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import Model

    return Model(ICASSP_2022_MODEL_PATH)


def _demucs_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"

    return "cuda" if torch.cuda.is_available() else "cpu"


def _separate_stems(
    audio_path: Path,
    output_directory: Path,
    model_name: str,
    cancel_event: Event | None = None,
    shifts: int = 1,
) -> Path:
    command = [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        model_name,
        "--shifts",
        str(shifts),
        "-d",
        _demucs_device(),
        "-o",
        str(output_directory),
        str(audio_path),
    ]
    if cancel_event is not None and cancel_event.is_set():
        raise TranscriptionCancelled("Transcription stopped.")

    process_options = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if sys.platform == "win32":
        process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_options["start_new_session"] = True

    process = subprocess.Popen(command, **process_options)
    deadline = time.monotonic() + 60 * 60

    def stop_process_tree() -> None:
        if process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            import os
            import signal

            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    output = ""
    while True:
        if cancel_event is not None and cancel_event.is_set():
            stop_process_tree()
            process.communicate()
            raise TranscriptionCancelled("Transcription stopped.")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop_process_tree()
            process.communicate()
            raise RuntimeError(
                "Stem separation took longer than one hour. Try a shorter audio file."
            )

        try:
            output, _ = process.communicate(timeout=min(0.5, remaining))
            break
        except subprocess.TimeoutExpired:
            continue

    if process.returncode != 0:
        details = (output or "").strip()
        details = details[-2500:] if details else "No details were returned."
        lowered_details = details.lower()
        if any(term in lowered_details for term in ("torchcodec", "avcodec", "ffmpeg")):
            raise RuntimeError(
                "Demucs could not decode the audio. Install the project dependencies "
                "with install.ps1 and make sure the FFmpeg shared build is on PATH, "
                "then restart the app.\n\n"
                f"{details}"
            )
        raise RuntimeError(
            "Demucs could not separate this audio. On the first run, an internet "
            "connection is needed to download its model weights. Details:\n\n"
            f"{details}"
        )

    model_directory = output_directory / model_name
    song_directories = sorted(path for path in model_directory.iterdir() if path.is_dir())
    if not song_directories:
        raise RuntimeError("Demucs finished, but no separated stems were found.")

    return song_directories[0]


def _make_monophonic(notes, prefer_high: bool):
    """Reduce overlapping notes to a single upper or lower line."""
    from pretty_midi import Note

    if not notes:
        return []

    boundaries = sorted(
        {
            float(point)
            for note in notes
            for point in (note.start, note.end)
            if note.end > note.start
        }
    )
    selected = []

    for start, end in zip(boundaries, boundaries[1:]):
        if end - start < 0.001:
            continue

        midpoint = (start + end) / 2
        active = [
            note
            for note in notes
            if note.start <= midpoint and note.end > midpoint
        ]
        if not active:
            continue

        chooser = max if prefer_high else min
        chosen = chooser(active, key=lambda note: (note.pitch, note.velocity))

        if (
            selected
            and selected[-1].pitch == chosen.pitch
            and start <= selected[-1].end + 0.025
        ):
            selected[-1].end = end
            selected[-1].velocity = max(selected[-1].velocity, chosen.velocity)
        else:
            selected.append(
                Note(
                    velocity=int(chosen.velocity),
                    pitch=int(chosen.pitch),
                    start=float(start),
                    end=float(end),
                )
            )

    return selected


def _quantize_notes(notes, bpm: float, grid: str):
    from pretty_midi import Note

    divisions = QUANTIZATION_DIVISIONS[grid]
    if divisions is None:
        return [
            Note(
                velocity=int(note.velocity),
                pitch=int(note.pitch),
                start=max(0.0, float(note.start)),
                end=float(note.end),
            )
            for note in notes
            if note.end > note.start
        ]

    seconds_per_grid_step = (60.0 / bpm) / divisions
    quantized = []

    for note in notes:
        start = max(
            0.0,
            round(float(note.start) / seconds_per_grid_step) * seconds_per_grid_step,
        )
        end = round(float(note.end) / seconds_per_grid_step) * seconds_per_grid_step
        if end <= start:
            end = start + seconds_per_grid_step

        quantized.append(
            Note(
                velocity=int(note.velocity),
                pitch=int(note.pitch),
                start=start,
                end=end,
            )
        )

    return quantized


def _peak_frames(flux, sample_rate: int, hop_length: int):
    """Find distinct transient peaks in one frequency band's spectral flux."""
    import numpy as np
    from scipy.signal import find_peaks

    if len(flux) < 3 or not np.any(flux > 0):
        return []

    smoothed = np.convolve(flux, np.array([0.25, 0.5, 0.25]), mode="same")
    peak_level = float(np.max(smoothed))
    median = float(np.median(smoothed))
    mad = float(np.median(np.abs(smoothed - median)))
    minimum_height = max(median + 1.25 * mad, peak_level * 0.025)
    minimum_gap = max(1, round(0.045 * sample_rate / hop_length))
    peaks, _ = find_peaks(
        smoothed,
        height=minimum_height,
        prominence=max(peak_level * 0.04, 1e-9),
        distance=minimum_gap,
    )
    return peaks.tolist()


def _drum_hit_pitch(audio, sample_rate: int, onset_time: float, lane: str):
    """Map a drum-stem transient to a simple General MIDI drum note."""
    import numpy as np

    start = max(0, int((onset_time - 0.008) * sample_rate))
    stop = min(len(audio), start + int(0.09 * sample_rate))
    segment = audio[start:stop]
    if len(segment) < int(0.025 * sample_rate):
        return None

    fft_size = 8192
    spectrum = np.abs(
        np.fft.rfft(segment * np.hanning(len(segment)), n=fft_size)
    ) ** 2
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    total_energy = float(np.sum(spectrum))
    if total_energy <= 1e-12:
        return None

    low = float(np.sum(spectrum[(frequencies >= 25) & (frequencies < 180)]))
    mid = float(np.sum(spectrum[(frequencies >= 180) & (frequencies < 5000)]))
    high = float(np.sum(spectrum[frequencies >= 5000]))
    low_ratio = low / total_energy
    mid_ratio = mid / total_energy
    high_ratio = high / total_energy

    if lane == "kick":
        return 36 if low_ratio >= 0.22 else None  # Bass Drum 1

    # A strong low end with little high-frequency energy is usually kick bleed.
    # Keep bright coincident hats so a kick-and-hat hit can produce both notes.
    if low_ratio >= 0.48 and high_ratio < 0.42:
        return None

    if high_ratio >= 0.45:
        attack_stop = min(len(segment), int(0.025 * sample_rate))
        tail_start = min(len(segment), int(0.055 * sample_rate))
        attack = float(np.sqrt(np.mean(segment[:attack_stop] ** 2)))
        tail = float(np.sqrt(np.mean(segment[tail_start:] ** 2))) if tail_start < len(segment) else 0.0
        return 46 if attack > 1e-8 and tail / attack >= 0.28 else 42  # Open/closed hat

    if mid_ratio >= 0.35:
        return 39 if high_ratio >= 0.16 else 38  # Hand clap / acoustic snare
    return 45  # Low tom as a readable fallback for other percussion


def _detect_drum_parts(audio_path: Path):
    """Extract simplified kick and percussion hits from Demucs' drum stem."""
    import librosa
    import numpy as np
    from pretty_midi import Note

    sample_rate = 22050
    hop_length = 256
    audio, _ = librosa.load(audio_path, sr=sample_rate, mono=True)
    empty = {"kick": [], "percussion": []}
    if audio.size < hop_length * 4 or not np.any(np.abs(audio) > 1e-8):
        return empty

    spectrum = np.abs(
        librosa.stft(audio, n_fft=2048, hop_length=hop_length)
    )
    positive_flux = np.maximum(spectrum[:, 1:] - spectrum[:, :-1], 0.0)
    positive_flux = np.pad(positive_flux, ((0, 0), (1, 0)))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
    low_bins = (frequencies >= 25) & (frequencies < 180)
    percussion_bins = frequencies >= 180
    band_flux = {
        "kick": np.sum(positive_flux[low_bins], axis=0),
        "percussion": np.sum(positive_flux[percussion_bins], axis=0),
    }

    parts = {"kick": [], "percussion": []}
    for lane, flux in band_flux.items():
        for frame in _peak_frames(flux, sample_rate, hop_length):
            onset_time = max(0.0, frame * hop_length / sample_rate - 0.006)
            pitch = _drum_hit_pitch(audio, sample_rate, onset_time, lane)
            if pitch is None:
                continue
            note_length = 0.09 if lane == "kick" else 0.07
            parts[lane].append(
                Note(
                    velocity=100,
                    pitch=pitch,
                    start=onset_time,
                    end=onset_time + note_length,
                )
            )

    return parts


def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    selected_parts: Sequence[str],
    simplification: str,
    quantization: str,
    bpm: float,
    model,
    separation_model: str = "htdemucs",
    separation_shifts: int = 1,
    pitch_sensitivity: str = "Balanced (recommended)",
    on_progress: Callable[[str, float], None] | None = None,
    cancel_event: Event | None = None,
) -> tuple[bytes, list[dict[str, str | int]]]:
    """Separate a techno mix into simple drum and pitched MIDI lanes."""
    import pretty_midi

    if not selected_parts:
        raise ValueError("Choose at least one part to include in the MIDI.")
    if simplification not in SIMPLIFICATION_MIN_SECONDS:
        raise ValueError("Choose a valid simplification level.")
    if quantization not in QUANTIZATION_DIVISIONS:
        raise ValueError("Choose a valid quantization grid.")
    if separation_model not in SEPARATION_MODELS.values():
        raise ValueError("Choose a valid stem separation model.")
    if not 1 <= separation_shifts <= 10:
        raise ValueError("Demucs shifts must be between 1 and 10.")
    if pitch_sensitivity not in PITCH_SENSITIVITY:
        raise ValueError("Choose a valid pitch detection sensitivity.")
    if bpm <= 0:
        raise ValueError("Tempo must be greater than zero.")

    extension = Path(filename).suffix.lower()
    if extension not in {".wav", ".mp3", ".flac", ".ogg"}:
        raise ValueError("Use a WAV, MP3, FLAC, or OGG audio file.")

    minimum_duration = SIMPLIFICATION_MIN_SECONDS[simplification]
    selected_parts = [part for part in selected_parts if part in PARTS]
    if not selected_parts:
        raise ValueError("No supported MIDI parts were selected.")
    needs_pitch_model = any(PARTS[part]["kind"] == "pitched" for part in selected_parts)
    if needs_pitch_model and model is None:
        raise ValueError("The pitch transcription model did not load. Restart the app and try again.")
    if needs_pitch_model:
        from basic_pitch.inference import predict

    def report(message: str, amount: float) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled("Transcription stopped.")
        if on_progress is not None:
            on_progress(message, amount)

    safe_stem = Path(filename).stem or "song"

    with tempfile.TemporaryDirectory(prefix="music_midi_") as temporary_directory:
        working_directory = Path(temporary_directory)
        audio_path = working_directory / f"input{extension}"
        audio_path.write_bytes(audio_bytes)

        report(
            f"Separating stems with {separation_model} ({separation_shifts} shifted "
            "pass(es)); this can take a while on CPU...",
            0.10,
        )
        separated_directory = _separate_stems(
            audio_path,
            working_directory / "separated",
            separation_model,
            cancel_event=cancel_event,
            shifts=separation_shifts,
        )

        midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
        summaries: list[dict[str, str | int]] = []
        progress_span = 0.76 / max(1, len(selected_parts))
        drum_parts = None

        for index, part_key in enumerate(selected_parts):
            part = PARTS[part_key]
            stem_path = separated_directory / part["stem"]
            if not stem_path.is_file():
                continue

            if part["kind"] == "drum":
                report(
                    f"Finding {part['track_name'].lower()} hits in the drum stem...",
                    0.22 + index * progress_span,
                )
                if drum_parts is None:
                    drum_parts = _detect_drum_parts(stem_path)
                    if cancel_event is not None and cancel_event.is_set():
                        raise TranscriptionCancelled("Transcription stopped.")
                notes = drum_parts[part["drum_lane"]]
            else:
                report(
                    f"Transcribing {part['track_name']} with Basic Pitch...",
                    0.22 + index * progress_span,
                )
                _, stem_midi, _ = predict(
                    str(stem_path),
                    model,
                    onset_threshold=PITCH_SENSITIVITY[pitch_sensitivity][0],
                    frame_threshold=PITCH_SENSITIVITY[pitch_sensitivity][1],
                    minimum_note_length=30.0,
                    minimum_frequency=part["minimum_frequency"],
                    maximum_frequency=part["maximum_frequency"],
                    midi_tempo=float(bpm),
                )
                if cancel_event is not None and cancel_event.is_set():
                    raise TranscriptionCancelled("Transcription stopped.")
                raw_notes = [
                    note
                    for instrument in stem_midi.instruments
                    for note in instrument.notes
                    if note.end - note.start >= minimum_duration
                    and part["minimum_pitch"] <= note.pitch <= part["maximum_pitch"]
                ]

                if part["line"] == "high":
                    notes = _make_monophonic(raw_notes, prefer_high=True)
                elif part["line"] == "low":
                    notes = _make_monophonic(raw_notes, prefer_high=False)
                else:
                    notes = raw_notes

            notes = _quantize_notes(notes, bpm, quantization)
            if not notes:
                continue

            instrument = pretty_midi.Instrument(
                program=part.get("program", 0),
                name=part["track_name"],
                is_drum=part["kind"] == "drum",
            )
            instrument.notes = notes
            midi.instruments.append(instrument)
            summaries.append(
                {
                    "MIDI track": part["track_name"],
                    "Notes": len(notes),
                    "Recommended instrument": part["recommended_instrument"],
                    "Recommended sound": part["recommended_sound"],
                }
            )

        if not midi.instruments:
            raise RuntimeError(
                "No MIDI events were detected in the selected parts. Try a less "
                "strict note cleanup setting or choose different parts."
            )

        report("Writing the separate MIDI tracks...", 0.96)
        output_path = working_directory / f"{safe_stem}_techno.mid"
        midi.write(str(output_path))
        midi_bytes = output_path.read_bytes()

    report("MIDI is ready.", 1.0)
    return midi_bytes, summaries
