# Luthence Sounds — Music MIDI Transcriber

> Portfolio README draft based on the local project README and source files. Confirm dependencies and local run instructions after making a clean public copy.

Luthence Sounds is a local Windows Streamlit studio for turning techno and hard-techno audio into editable, multi-track MIDI. It also renders SoundFont-based MP3 previews from generated MIDI.

## How it works

- Demucs separates broad stems: drums, bass, vocals, and other.
- Basic Pitch transcribes pitched stems; frequency-aware transient detection estimates kick and percussion hits.
- Note cleanup, BPM, quantization, and separation-quality settings let the user trade detail for speed or fewer artifacts.
- Exports include a combined MIDI, separate MIDI lanes, and optional MP3 previews.

MIDI stores notes and timing rather than the original instrument audio. The broad “other” stem combines synths, leads, chords, pads, and effects; drum hits and note events are estimates and need listening review.

## Optional prompt-to-audio feature

The app has a separate ACE-Step panel that sends a text prompt to fal.ai and returns generated audio. This feature does not transcribe audio or create MIDI. It requires a fal.ai API key and may incur usage charges. Never commit API keys; include only a placeholder configuration example.

## Requirements and local run

The project README specifies 64-bit Python 3.11 on Windows, FFmpeg shared libraries, and model-weight downloads on first use. After confirming the curated copy and dependencies, the documented local commands are:

```powershell
.\install.ps1
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

CPU processing is supported; a compatible NVIDIA GPU can use CUDA. Processing and quality modes can take substantial time and memory.

## Rights and limitations

- Only upload music that you have permission to process.
- The SoundFont is downloaded on demand rather than bundled. See `SOUNDFONT_NOTICE.md` and review its license before redistributing it.
- Keep `.venv`, logs, generated audio/MIDI, cached model weights, Streamlit secrets, and API keys out of Git.
- Do not claim perfect transcription. Review the output in a DAW and compare it with the source.

## License

Add a license for this project's code after confirming ownership and permissions. Keep third-party model, SoundFont, and dependency notices alongside the project.
