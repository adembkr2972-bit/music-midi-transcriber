from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import Event, Lock, Thread

import streamlit as st

from music_midi.audio_export import (
    DEFAULT_SOUNDFONT_SHA256,
    build_export_zip,
    get_default_soundfont_bytes,
    render_track_to_mp3,
    split_midi_tracks,
)
from music_midi.pipeline import (
    PARTS,
    PITCH_SENSITIVITY,
    SEPARATION_MODELS,
    SEPARATION_SHIFTS,
    TranscriptionCancelled,
    transcribe_audio,
)
from music_midi.prompt_music import (
    PRICE_PER_SECOND_USD,
    MusicGenerationError,
    generate_prompt_track,
)


st.set_page_config(
    page_title="Luthence Sounds | MIDI Studio",
    page_icon="🎛️",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        color-scheme: dark;
        --luthence-bg: #070b13;
        --luthence-panel: #0d1421;
        --luthence-panel-raised: #111c2d;
        --luthence-blue: #4f91ff;
        --luthence-cyan: #61d4ff;
        --luthence-text: #eef4ff;
        --luthence-muted: #9aa9c1;
        --luthence-line: rgba(137, 169, 216, 0.16);
    }

    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(ellipse at 12% 0%, rgba(31, 87, 177, 0.24), transparent 38%),
            radial-gradient(ellipse at 100% 18%, rgba(27, 76, 146, 0.12), transparent 32%),
            linear-gradient(180deg, #090e18 0%, var(--luthence-bg) 62%);
        color: var(--luthence-text);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"] {
        max-width: 1080px;
        padding-top: 1.7rem;
        padding-bottom: 4rem;
    }

    .luthence-logo {
        width: min(100%, 390px);
        margin: 0 0 1.3rem 0;
        filter: drop-shadow(0 10px 28px rgba(25, 91, 190, 0.16));
    }

    .luthence-logo svg {
        display: block;
        width: 100%;
        height: auto;
    }

    .luthence-hero {
        padding: 1.15rem 0 1.5rem;
        margin-bottom: 0.7rem;
    }

    .luthence-kicker {
        color: var(--luthence-cyan);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.17em;
        text-transform: uppercase;
        margin: 0 0 0.7rem;
    }

    .luthence-hero h1 {
        color: var(--luthence-text);
        font-size: clamp(2.25rem, 6vw, 3.8rem);
        line-height: 1.04;
        letter-spacing: -0.055em;
        font-weight: 750;
        margin: 0;
        max-width: 780px;
    }

    .luthence-hero p {
        color: #b2bfd3;
        font-size: 1.08rem;
        line-height: 1.65;
        max-width: 690px;
        margin: 1rem 0 0;
    }

    .luthence-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 0.55rem;
        margin-top: 1.25rem;
    }

    .luthence-tags span {
        color: #c4d8f7;
        background: rgba(23, 44, 76, 0.55);
        border: 1px solid rgba(97, 153, 232, 0.2);
        border-radius: 999px;
        padding: 0.38rem 0.72rem;
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        font-weight: 650;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(145deg, rgba(17, 27, 43, 0.9), rgba(10, 16, 27, 0.9));
        border: 1px solid var(--luthence-line);
        border-radius: 20px;
        box-shadow: 0 18px 50px rgba(0, 0, 0, 0.14);
    }

    [data-testid="stForm"] {
        background: linear-gradient(155deg, rgba(15, 24, 39, 0.96), rgba(9, 14, 24, 0.98));
        border: 1px solid rgba(105, 150, 214, 0.21);
        border-radius: 24px;
        padding: 1.15rem 1.3rem 1.25rem;
        box-shadow: 0 24px 70px rgba(0, 0, 0, 0.25);
    }

    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4 {
        color: var(--luthence-text);
        letter-spacing: -0.025em;
    }

    [data-testid="stMarkdownContainer"] h4 {
        font-size: 1rem;
        margin-top: 1rem;
        margin-bottom: 0.8rem;
    }

    [data-testid="stCaptionContainer"] {
        color: var(--luthence-muted);
    }

    [data-testid="stWidgetLabel"] p {
        color: #d6e2f4;
        font-weight: 600;
    }

    [data-testid="stFileUploaderDropzone"] {
        background: rgba(13, 25, 43, 0.7);
        border: 1px dashed rgba(94, 156, 239, 0.46);
        border-radius: 16px;
    }

    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--luthence-cyan);
        background: rgba(18, 37, 64, 0.72);
    }

    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    [data-testid="stNumberInput"] button {
        background: #0d1726;
        border-color: rgba(133, 163, 205, 0.25);
        border-radius: 12px;
    }

    [data-testid="stMultiSelect"] [data-baseweb="select"] > div {
        background: #0d1726;
        border-radius: 12px;
    }

    [data-testid="stButton"] button,
    [data-testid="stDownloadButton"] button,
    [data-testid="stFormSubmitButton"] button {
        border-radius: 12px;
        min-height: 2.8rem;
        font-weight: 650;
        transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
    }

    [data-testid="stFormSubmitButton"] button,
    [data-testid="stButton"] button[kind="primary"] {
        color: #06101e;
        border: 0;
        background: linear-gradient(105deg, #65c8ff 0%, #4a91ff 52%, #5478ff 100%);
        box-shadow: 0 8px 24px rgba(50, 124, 231, 0.22);
    }

    [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stButton"] button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 30px rgba(50, 124, 231, 0.35);
    }

    [data-testid="stDownloadButton"] button {
        color: #dceaff;
        background: rgba(20, 39, 64, 0.8);
        border: 1px solid rgba(91, 148, 223, 0.32);
    }

    [data-testid="stDownloadButton"] button:hover,
    [data-testid="stButton"] button:hover {
        border-color: rgba(97, 212, 255, 0.75);
        color: #ffffff;
    }

    [data-testid="stExpander"] {
        background: rgba(12, 19, 31, 0.7);
        border: 1px solid var(--luthence-line);
        border-radius: 16px;
    }

    [data-testid="stAlert"] {
        border-radius: 14px;
        border: 1px solid rgba(105, 150, 214, 0.2);
    }

    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="menu"] {
        background: #101a2a;
        border: 1px solid var(--luthence-line);
        border-radius: 12px;
    }

    [data-baseweb="tag"] {
        color: #e8f2ff;
        background: #173153;
        border: 1px solid rgba(97, 153, 232, 0.22);
    }

    [data-testid="stProgress"] > div > div > div > div {
        background: linear-gradient(90deg, #4e8eff, #61d4ff);
    }

    hr {
        border-color: rgba(131, 163, 207, 0.14);
    }

    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 1rem;
        }
        [data-testid="stForm"] {
            padding: 0.8rem;
            border-radius: 18px;
        }
        .luthence-hero p { font-size: 0.98rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

logo_svg = (Path(__file__).parent / "assets" / "luthence_sounds_logo.svg").read_text(
    encoding="utf-8"
)
st.markdown(f'<div class="luthence-logo">{logo_svg}</div>', unsafe_allow_html=True)
st.markdown(
    """
    <div class="luthence-hero">
      <div class="luthence-kicker">Audio to MIDI workspace</div>
      <h1>From sound to MIDI.</h1>
      <p>Shape techno and hard techno into clear, editable lanes for Ableton Live and your other favorite DAWs.</p>
      <div class="luthence-tags">
        <span>LOCAL PROCESSING</span>
        <span>SEPARATE LANES</span>
        <span>MIDI + MP3</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container(border=True):
    feature_columns = st.columns(3)
    with feature_columns[0]:
        st.caption("01 / RHYTHM")
        st.markdown("**Kick + percussion**")
        st.caption("Transient-based lanes for the hard techno foundation.")
    with feature_columns[1]:
        st.caption("02 / PITCH")
        st.markdown("**Bass + synths**")
        st.caption("Editable notes from the separated pitched stems.")
    with feature_columns[2]:
        st.caption("03 / EXPORT")
        st.markdown("**Ready for your DAW**")
        st.caption("Separate MIDI files and optional SoundFont MP3 previews.")
    st.caption(
        "Synth, lead, pad, chord, and effect sounds stay grouped in the source model's "
        "broad synth stem. Drum hits are estimates and can be edited after export."
    )

class TranscriptionJob:
    """Thread-safe progress and cancellation state for one user session."""

    def __init__(self) -> None:
        self.cancel_event = Event()
        self.done_event = Event()
        self._lock = Lock()
        self.status = "running"
        self.progress = 0.0
        self.message = "Starting transcription..."
        self.result = None
        self.error = None

    def update_progress(self, message: str, amount: float) -> None:
        with self._lock:
            if self.cancel_event.is_set():
                self.status = "cancelling"
                self.message = "Stopping transcription..."
                return
            self.message = message
            self.progress = amount

    def request_cancel(self) -> None:
        if self.done_event.is_set():
            return
        self.cancel_event.set()
        with self._lock:
            if not self.done_event.is_set():
                self.status = "cancelling"
                self.message = "Stopping transcription..."

    def finish(self, status: str, result=None, error: str | None = None) -> None:
        with self._lock:
            if status == "complete" and self.cancel_event.is_set():
                status = "cancelled"
            self.status = status
            self.result = result if status == "complete" else None
            self.error = error
            if status == "complete":
                self.progress = 1.0
                self.message = "MIDI is ready."
            elif status == "cancelled":
                self.message = "Transcription stopped."
            elif status == "error":
                self.message = "Transcription could not be completed."
            self.done_event.set()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
                "result": self.result,
                "error": self.error,
            }


def run_transcription_job(
    job: TranscriptionJob,
    *,
    audio_bytes: bytes,
    filename: str,
    selected_parts: list[str],
    simplification: str,
    quantization: str,
    bpm: float,
    model,
    separation_model: str,
    separation_shifts: int,
    pitch_sensitivity: str,
    result_name: str,
) -> None:
    try:
        midi_bytes, track_summaries = transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            selected_parts=selected_parts,
            simplification=simplification,
            quantization=quantization,
            bpm=bpm,
            model=model,
            separation_model=separation_model,
            separation_shifts=separation_shifts,
            pitch_sensitivity=pitch_sensitivity,
            on_progress=job.update_progress,
            cancel_event=job.cancel_event,
        )
    except TranscriptionCancelled:
        job.finish("cancelled")
    except Exception as exc:
        if job.cancel_event.is_set():
            job.finish("cancelled")
        else:
            job.finish("error", error=str(exc))
    else:
        job.finish(
            "complete",
            result={
                "midi": midi_bytes,
                "filename": result_name,
                "tracks": track_summaries,
            },
        )


st.session_state.setdefault("transcription_result", None)
st.session_state.setdefault("transcription_job", None)
st.session_state.setdefault("transcription_notice", None)
st.session_state.setdefault("mp3_exports", {})
st.session_state.setdefault("mp3_source_signature", None)
st.session_state.setdefault("prompt_music_result", None)


@st.cache_resource(show_spinner=False)
def get_basic_pitch_model():
    from music_midi.pipeline import load_basic_pitch_model

    return load_basic_pitch_model()


@st.cache_data(show_spinner=False)
def cached_track_exports(midi_data: bytes, filename: str):
    return split_midi_tracks(midi_data, filename)


@st.fragment(run_every="1s")
def show_transcription_progress() -> None:
    job = st.session_state.get("transcription_job")
    if job is None:
        return

    snapshot = job.snapshot()
    if job.done_event.is_set():
        if snapshot["status"] == "complete":
            st.session_state["transcription_result"] = snapshot["result"]
            st.session_state["transcription_notice"] = (
                "success",
                "Your multi-track MIDI is ready.",
            )
        elif snapshot["status"] == "cancelled":
            st.session_state["transcription_notice"] = (
                "info",
                "Transcription stopped. No MIDI was created.",
            )
        else:
            st.session_state["transcription_result"] = None
            st.session_state["transcription_notice"] = (
                "error",
                snapshot["error"] or "Transcription could not be completed.",
            )
        st.session_state["transcription_job"] = None
        st.rerun()

    with st.container(border=True):
        st.subheader("Transcription in progress")
        st.progress(
            float(snapshot["progress"]),
            text=str(snapshot["message"]),
        )
        if snapshot["status"] == "cancelling":
            st.info(
                "Stop requested. Demucs will stop shortly. If audio analysis is "
                "in progress, it will finish its current step first."
            )
        elif st.button(
            "Stop transcription",
            type="secondary",
            icon=":material/stop:",
            key="stop_transcription",
        ):
            job.request_cancel()
            st.info("Stop requested. The current analysis step is stopping.")

transcription_tab, music_tab = st.tabs(
    ["Transcribe to MIDI", "Create music"],
    key="studio_section",
    on_change="rerun",
)

if transcription_tab.open:
    with transcription_tab:
        active_job = st.session_state.get("transcription_job")
        job_is_active = active_job is not None

        with st.form("transcription_form"):
            st.markdown("#### 01 / Source and lanes")
            uploaded_file = st.file_uploader(
                "Choose a song",
                type=["wav", "mp3", "flac", "ogg"],
                help="Use an audio file stored on your computer. Processing happens locally.",
            )

            selected_parts = st.multiselect(
                "MIDI tracks to create",
                options=list(PARTS),
                default=["kick", "percussion", "bass", "synths"],
                format_func=lambda key: PARTS[key]["track_name"],
                help="Choose which separated techno parts to include in the MIDI file.",
            )

            st.markdown("#### 02 / Transcription detail")
            detail_left, detail_right = st.columns(2)
            with detail_left:
                simplification = st.select_slider(
                    "Note cleanup",
                    options=["Light", "Balanced", "Strong"],
                    value="Light",
                    help="Light keeps fast techno sequences. Strong removes more short stabs and repeats.",
                )

                pitch_sensitivity = st.selectbox(
                    "Pitched-track sensitivity",
                    options=list(PITCH_SENSITIVITY),
                    index=0,
                    help=(
                        "More sensitive can recover quiet notes but may add harmonics or bleed. "
                        "More conservative can miss quiet notes."
                    ),
                )

            with detail_right:
                quantization = st.selectbox(
                    "Note grid",
                    options=["Off", "Eighth notes", "Sixteenth notes", "Thirty-second notes"],
                    index=0,
                    help="Quantization can tighten timing, but may move notes if the tempo is wrong.",
                )

                separation_mode = st.selectbox(
                    "Stem separation quality",
                    options=list(SEPARATION_MODELS),
                    index=0,
                    help=(
                        "Fast uses one standard Demucs pass. Higher quality uses the fine-tuned "
                        "model. Highest quality averages 10 shifted predictions and can take "
                        "many times longer, especially on CPU."
                    ),
                )

            st.markdown("#### 03 / Timing")
            bpm = st.number_input(
                "Song tempo (BPM)",
                min_value=40,
                max_value=240,
                value=145,
                step=1,
                help="Sets the MIDI tempo. It also controls note snapping when you choose a grid, so enter the song's BPM for tight alignment.",
            )

            submitted = st.form_submit_button(
                "Generate MIDI tracks",
                type="primary",
                icon=":material/music_note:",
                disabled=job_is_active,
            )

        if submitted:
            if job_is_active:
                st.info("Wait for the current transcription to stop or finish.")
            elif uploaded_file is None:
                st.error("Choose an audio file first.")
            elif not selected_parts:
                st.error("Select at least one MIDI track.")
            elif uploaded_file.size > 200 * 1024 * 1024:
                st.error("This first version supports files up to 200 MB.")
            else:
                file_stem = Path(uploaded_file.name).stem or "song"
                result_name = f"{file_stem}_techno.mid"
                audio_bytes = uploaded_file.getvalue()
                st.session_state["transcription_result"] = None
                st.session_state["transcription_notice"] = None
                st.session_state["mp3_exports"] = {}
                st.session_state["mp3_source_signature"] = None
                needs_pitch_model = any(
                    PARTS[key]["kind"] == "pitched" for key in selected_parts
                )

                try:
                    if needs_pitch_model:
                        with st.spinner("Loading the pitch model..."):
                            model = get_basic_pitch_model()
                    else:
                        model = None
                except Exception as exc:
                    st.error(f"The pitch model could not be loaded: {exc}")
                else:
                    job = TranscriptionJob()
                    st.session_state["transcription_job"] = job
                    worker = Thread(
                        target=run_transcription_job,
                        kwargs={
                            "job": job,
                            "audio_bytes": audio_bytes,
                            "filename": uploaded_file.name,
                            "selected_parts": list(selected_parts),
                            "simplification": simplification,
                            "quantization": quantization,
                            "bpm": float(bpm),
                            "model": model,
                            "separation_model": SEPARATION_MODELS[separation_mode],
                            "separation_shifts": SEPARATION_SHIFTS[separation_mode],
                            "pitch_sensitivity": pitch_sensitivity,
                            "result_name": result_name,
                        },
                        name="music-midi-transcription",
                        daemon=True,
                    )
                    worker.start()

        notice = st.session_state.get("transcription_notice")
        if notice:
            notice_kind, notice_message = notice
            if notice_kind == "success":
                st.success(notice_message)
            elif notice_kind == "error":
                st.error(notice_message)
            else:
                st.info(notice_message)

        if st.session_state.get("transcription_job") is not None:
            show_transcription_progress()


        result = st.session_state.get("transcription_result")
        if result:
            st.divider()
            st.subheader("Your generated lanes")
            track_exports = cached_track_exports(result["midi"], result["filename"])
            track_exports_by_name = {track["name"]: track for track in track_exports}

            with st.expander("MP3 sound and export settings"):
                st.write(
                    "MP3 files are audio previews rendered from the MIDI with a General MIDI "
                    "SoundFont. They do not include the original song audio or reproduce an "
                    "Ableton instrument preset. Upload a compatible `.sf2` SoundFont to use "
                    "your own sounds."
                )
                soundfont_upload = st.file_uploader(
                    "Optional custom SoundFont (.sf2)",
                    type=["sf2"],
                    key="mp3_soundfont_upload",
                    help="A General MIDI SoundFont gives the most reliable program mapping. "
                    "Custom SoundFonts can use different presets or drum layouts.",
                )
                custom_soundfont = soundfont_upload.getvalue() if soundfont_upload else None
                soundfont_signature = (
                    f"custom:{hashlib.sha256(custom_soundfont).hexdigest()}"
                    if custom_soundfont
                    else f"default:{DEFAULT_SOUNDFONT_SHA256}"
                )
                if st.session_state["mp3_source_signature"] != soundfont_signature:
                    st.session_state["mp3_exports"] = {}
                    st.session_state["mp3_source_signature"] = soundfont_signature

                st.caption(
                    "Previews are peak-normalized to -1 dBFS for headroom and encoded as "
                    "stereo 48 kHz / 320 kbps MP3. The default GeneralUser GS SoundFont is "
                    "downloaded once on the first "
                    "render (about 31 MB) and cached on this computer. An internet connection "
                    "is needed for that first download."
                )
                st.caption(
                    "GeneralUser GS by S. Christian Collins is used under its published "
                    "license. See the [project and license](https://github.com/planet-s/generaluser-gs)."
                )

                renderable_tracks = [track for track in track_exports if track["note_count"]]
                missing_mp3_tracks = [
                    track
                    for track in renderable_tracks
                    if track["filename"] not in st.session_state["mp3_exports"]
                ]
                if missing_mp3_tracks and st.button(
                    "Render all MP3 tracks",
                    key="render_all_mp3_tracks",
                    help="Creates a separate 48 kHz, 320 kbps MP3 preview for each track with notes.",
                ):
                    try:
                        with st.spinner("Loading SoundFont and rendering MP3 previews..."):
                            soundfont_bytes = (
                                custom_soundfont
                                if custom_soundfont is not None
                                else get_default_soundfont_bytes()
                            )
                            progress = st.progress(0.0, text="Preparing SoundFont renderer...")
                            for index, track_export in enumerate(missing_mp3_tracks, start=1):
                                progress.progress(
                                    (index - 1) / len(missing_mp3_tracks),
                                    text=f"Rendering {track_export['name']}...",
                                )
                                mp3_data = render_track_to_mp3(
                                    track_export["midi"], soundfont_bytes
                                )
                                exports = st.session_state["mp3_exports"].copy()
                                exports[track_export["filename"]] = mp3_data
                                st.session_state["mp3_exports"] = exports
                        progress.progress(1.0, text="MP3 previews are ready.")
                        st.success("Separate MP3 previews are ready to download below.")
                    except Exception as exc:
                        st.error(f"MP3 rendering failed: {exc}")

                rendered_mp3s = [
                    {**track, "mp3": st.session_state["mp3_exports"][track["filename"]]}
                    for track in renderable_tracks
                    if track["filename"] in st.session_state["mp3_exports"]
                ]
                if rendered_mp3s:
                    st.download_button(
                        "Download rendered MP3 tracks (.zip)",
                        data=build_export_zip(rendered_mp3s, "mp3"),
                        file_name=Path(result["filename"]).with_suffix(".mp3.zip").name,
                        mime="application/zip",
                        key="download_mp3_tracks_zip",
                    )

            part_details_by_name = {
                part["track_name"]: part for part in PARTS.values()
            }
            for track in result["tracks"]:
                part = part_details_by_name.get(track["MIDI track"], {})
                track_export = track_exports_by_name.get(track["MIDI track"])
                recommended_instrument = track.get(
                    "Recommended instrument", part.get("recommended_instrument")
                )
                recommended_sound = track.get(
                    "Recommended sound", part.get("recommended_sound")
                )
                with st.container(border=True):
                    st.markdown(f"**{track['MIDI track']}** — {track['Notes']} notes")
                    if recommended_instrument:
                        st.caption(f"Recommended instrument: {recommended_instrument}")
                    if recommended_sound:
                        st.write(recommended_sound)
                    if track_export:
                        st.download_button(
                            "Download MIDI track",
                            data=track_export["midi"],
                            file_name=track_export["filename"],
                            mime="audio/midi",
                            key=f"download_midi_track_{track_export['filename']}",
                        )
                        if track_export["note_count"] == 0:
                            st.caption("This track has no notes to render as audio.")
                        elif track_export["filename"] in st.session_state["mp3_exports"]:
                            st.download_button(
                                "Download MP3 preview",
                                data=st.session_state["mp3_exports"][track_export["filename"]],
                                file_name=Path(track_export["filename"]).with_suffix(".mp3").name,
                                mime="audio/mpeg",
                                key=f"download_mp3_track_{track_export['filename']}",
                            )
                        elif st.button(
                            "Render MP3 preview",
                            key=f"render_mp3_track_{track_export['filename']}",
                            help="Renders only this MIDI track as a 48 kHz, 320 kbps MP3 preview.",
                        ):
                            try:
                                with st.spinner(
                                    f"Loading SoundFont and rendering {track_export['name']} MP3..."
                                ):
                                    soundfont_bytes = (
                                        custom_soundfont
                                        if custom_soundfont is not None
                                        else get_default_soundfont_bytes()
                                    )
                                    mp3_data = render_track_to_mp3(
                                        track_export["midi"], soundfont_bytes
                                    )
                                exports = st.session_state["mp3_exports"].copy()
                                exports[track_export["filename"]] = mp3_data
                                st.session_state["mp3_exports"] = exports
                                st.download_button(
                                    "Download MP3 preview",
                                    data=mp3_data,
                                    file_name=Path(track_export["filename"]).with_suffix(".mp3").name,
                                    mime="audio/mpeg",
                                    key=f"download_mp3_track_{track_export['filename']}",
                                )
                            except Exception as exc:
                                st.error(f"MP3 rendering failed: {exc}")
            st.download_button(
                "Download MIDI",
                data=result["midi"],
                file_name=result["filename"],
                mime="audio/midi",
                type="primary",
                icon=":material/download:",
            )
            st.download_button(
                "Download separate MIDI tracks (.zip)",
                data=build_export_zip(track_exports, "midi"),
                file_name=Path(result["filename"]).with_suffix(".zip").name,
                mime="application/zip",
                key="download_midi_tracks_zip",
            )
            st.caption(
                "MIDI contains note data, not audio samples. Pitched tracks include "
                "General MIDI program hints, but you may need to load instruments in "
                "your DAW; use the suggestions above as a starting point."
            )
            st.caption(
                "Kick is MIDI note 36. Percussion notes are 38/39 (snare/clap), 42/46 "
                "(closed/open hat), and 45 (tom), which you can map to Drum Rack pads."
            )

        with st.expander("Accuracy and model limits"):
            st.write(
                "For difficult mixes, choose the highest stem-separation setting and adjust "
                "pitched-track sensitivity. More sensitivity can recover quiet notes but may "
                "add harmonics or stem bleed. The highest separation setting takes much "
                "longer and still cannot recover details missing from the separated audio."
            )
            st.write(
                "This profile uses HTDemucs for four broad sources: drums, bass, vocals, "
                "and other. The kick/percussion lanes are estimated from transients in the "
                "drum stem. Bass, synth, and optional vocal notes are transcribed from their "
                "separated stems. Separation can leave bleed or artifacts, especially on "
                "dense hard techno."
            )
            st.write(
                "Synth, lead, pad, chord, and effect sounds remain together in the 'other' "
                "stem. These models do not identify exact synth patches or guarantee a "
                "perfect transcription."
            )

if music_tab.open:
    with music_tab:
        def configured_fal_key() -> str:
            key = os.environ.get("FAL_KEY", "").strip()
            if key:
                return key
            try:
                return str(st.secrets.get("FAL_KEY", "")).strip()
            except Exception:
                return ""


        with st.expander(
            "Create music from a prompt",
            expanded=st.session_state.get("prompt_music_result") is not None,
        ):
            st.subheader("Make a new techno track")
            st.caption(
                "Describe the sound you want and create a downloadable audio track. "
                "This generates audio; it does not create MIDI or separate instrument stems."
            )
            st.info(
                "This generator sends your prompt and settings to ACE-Step through fal.ai. "
                f"Current model pricing is ${PRICE_PER_SECOND_USD:.4f} per second; "
                "a 60-second track is about $0.012, billed to your fal.ai account.",
                icon=":material/cloud_upload:",
            )

            fal_key = configured_fal_key()
            if fal_key:
                st.caption("Using the FAL_KEY configured for this app.")
            else:
                fal_key = st.text_input(
                    "fal.ai API key",
                    type="password",
                    key="prompt_music_api_key",
                    help="The key stays in this browser session and is not written to the project files.",
                ).strip()
                st.caption("Get an API key from [fal.ai](https://fal.ai/dashboard/keys).")

            prompt = st.text_area(
                "Describe your track",
                value=(
                    "Driving hard techno with a distorted punchy kick, rolling rumble bass, "
                    "hypnotic industrial synths, tight percussion, a dark warehouse atmosphere, "
                    "and a polished club mix."
                ),
                max_chars=1200,
                height=115,
                key="prompt_music_description",
                help="Include mood, sound design, arrangement, and (for vocals) the lyrical theme.",
            )

            music_left, music_right = st.columns(2)
            with music_left:
                prompt_style = st.selectbox(
                    "Techno direction",
                    [
                        "Hard techno",
                        "Industrial hard techno",
                        "Acid techno",
                        "Hypnotic techno",
                        "Melodic techno",
                    ],
                    key="prompt_music_style",
                )
                prompt_bpm = st.slider(
                    "Tempo",
                    min_value=120,
                    max_value=180,
                    value=145,
                    step=1,
                    format="%d BPM",
                    key="prompt_music_bpm",
                )
            with music_right:
                prompt_vocal_mode = st.selectbox(
                    "Vocal mode",
                    ["Instrumental", "Generated vocals"],
                    key="prompt_music_vocal_mode",
                    help="When enabled, ACE-Step generates vocals from the prompt and its lyrical theme.",
                )
                prompt_duration = st.slider(
                    "Track length",
                    min_value=30,
                    max_value=180,
                    value=60,
                    step=15,
                    format="%d seconds",
                    key="prompt_music_duration",
                )

            estimated_cost = prompt_duration * PRICE_PER_SECOND_USD
            st.caption(
                f"Estimated model charge: **${estimated_cost:.3f}** for {prompt_duration} seconds. "
                "[See fal.ai pricing](https://fal.ai/pricing)."
            )

            generate_prompt = st.button(
                f"Generate track · about ${estimated_cost:.3f}",
                type="primary",
                icon=":material/graphic_eq:",
                key="generate_prompt_track",
            )

            if generate_prompt:
                if not fal_key:
                    st.error("Add a fal.ai API key to generate a track.")
                elif len(prompt.strip()) < 8:
                    st.error("Add a little more detail to the track description.")
                else:
                    st.session_state["prompt_music_result"] = None
                    complete_prompt = (
                        f"{prompt_style}, {prompt_bpm} BPM. {prompt.strip()}"
                    )
                    try:
                        with st.status("Sending the prompt to ACE-Step...", expanded=False) as generation_status:
                            def update_generation_status(status: str, elapsed: float) -> None:
                                if status == "IN_QUEUE":
                                    label = f"Waiting for a generation slot · {int(elapsed)}s"
                                else:
                                    label = f"Creating your track · {int(elapsed)}s"
                                generation_status.update(label=label, state="running")

                            generated_track = generate_prompt_track(
                                api_key=fal_key,
                                prompt=complete_prompt,
                                instrumental=prompt_vocal_mode == "Instrumental",
                                duration_seconds=prompt_duration,
                                on_status=update_generation_status,
                            )
                            st.session_state["prompt_music_result"] = {
                                **generated_track,
                                "prompt": complete_prompt,
                                "duration": prompt_duration,
                                "vocal_mode": prompt_vocal_mode,
                            }
                            generation_status.update(
                                label="Your track is ready.",
                                state="complete",
                                expanded=False,
                            )
                    except MusicGenerationError as exc:
                        generation_status.update(
                            label="Track generation failed.",
                            state="error",
                            expanded=True,
                        )
                        st.error(str(exc))

            prompt_music_result = st.session_state.get("prompt_music_result")
            if prompt_music_result:
                st.divider()
                st.markdown("#### Your generated track")
                st.audio(
                    prompt_music_result["audio_bytes"],
                    format=prompt_music_result["content_type"],
                    alt="Preview of the generated techno track",
                )
                st.download_button(
                    "Download audio",
                    data=prompt_music_result["audio_bytes"],
                    file_name=prompt_music_result["filename"],
                    mime=prompt_music_result["content_type"],
                    icon=":material/download:",
                    key="download_prompt_music",
                )
                track_details = (
                    f"{prompt_music_result['duration']} seconds · "
                    f"{prompt_music_result['vocal_mode']}"
                )
                if prompt_music_result.get("seed") is not None:
                    track_details += f" · seed {prompt_music_result['seed']}"
                st.caption(track_details)
                with st.expander("Prompt used"):
                    st.write(prompt_music_result["prompt"])
