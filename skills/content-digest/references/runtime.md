# Runtime and setup

The Skill is self-contained apart from explicit tools and a separately downloaded model. Run commands below from this Skill directory, the directory containing `SKILL.md`. If the Skill is installed elsewhere, use its resolved absolute path; do not assume a personal project location.

## Text and reader route

Python 3.12+ is sufficient; these two scripts use the standard library:

```bash
python3 scripts/import_text.py /path/to/transcript.txt \
  --title "Episode title" --output /path/to/new-result
```

The output directory must be empty. SRT imports preserve supplied times; TXT imports set times to null. The helper writes transcript attachments, the reading index, and task state. It does not summarize. Read the complete indexed text and write `digest.json` using the [schema](page-schema.md), then:

```bash
python3 scripts/build_reader.py /path/to/new-result/digest.json
```

The HTML embeds its reading content. Keep `transcript.md` alongside the page to preserve the full-transcript attachment. An explicit `--output` location uses a relative link back to that attachment.

## Audio route: macOS or Linux

Install missing dependencies once, using their official instructions:

- Python 3.12+.
- Node.js 22+ for yt-dlp's configured JavaScript runtime. Check [current EJS requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS) if acquisition fails.
- [FFmpeg](https://ffmpeg.org/download.html), including `ffprobe`.
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp), exposing `whisper-cli` in `PATH`.
- A whisper.cpp GGML model. The original local workflow used `ggml-large-v3-turbo-q5_0.bin`; choose a model appropriate for your hardware from the [upstream model repository](https://huggingface.co/ggerganov/whisper.cpp/tree/main). Model weights are not included or downloaded automatically.

Create an environment in the installed Skill directory or another chosen location:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/transcribe.py 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --model /absolute/path/to/ggml-model.bin --output ./results
```

Replace the example URL and model path with real values. Alternatively set `CONTENT_DIGEST_MODEL` to your existing model file. The result is a source-specific subdirectory under the selected output path.

The dependency versions in `requirements.txt` match the original workflow. Platform extraction behavior can change; inspect the actual error before deliberately updating yt-dlp. Do not upgrade everything on each run.

## Options

| Option | Behavior |
| --- | --- |
| `--language auto`, `zh`, `en` | Recognition language; transcripts remain in the source language |
| `--output PATH` | Result root; defaults to `./content-digest-results` in the invocation directory |
| `--work-root PATH` | Marked temporary jobs; defaults to `./content-digest-results/.work` |
| `--model PATH` | Existing whisper.cpp GGML model; otherwise uses `CONTENT_DIGEST_MODEL` |
| `--chunk-seconds 600` | Ten-minute core chunks with two-second boundary overlap |
| `--no-gpu` | Explicit CPU fallback; first distinguish GPU permissions from model errors |
| `--limit-seconds 30` | Test excerpt, explicitly marked incomplete; never silently shorten a real request |
| `--clean-only` | Remove only this tool's marked inactive temporary jobs |
| `--cookies-from-browser NAME` | Only after explicit permission to read that browser's login state |

The script uses Unix `fcntl` locking. Native Windows transcription is not supported. macOS and Linux are the intended runtimes, with release-specific test coverage documented separately.

## State and failure

Progress is printed during transcription. The final success line is JSON; `task-state.json` records stages and status:

- `transcribed`: all audio was processed; summarization remains pending.
- `sample_transcribed`: a test excerpt, not a full transcript.
- `text_imported`: supplied text is ready for reading; no audio recognition is implied.
- `failed` / `cancelled`: do not claim a complete transcript or invent a digest.
- `summary_status=pending/complete`: the agent updates this after content and interaction checks.

Overlapping identical boundary text is merged; ambiguous alternatives are preserved with review notes. `reading-index.json` points into the final `transcript.txt`, avoiding redundant text slices.

Stop blind retries on HTTP 403/429, login requirements, or bot checks. Browser credentials are not an automatic workaround, and Whisper cannot repair access restrictions. A failed download and a successful local reader test are separate results.

The script does not upload audio or call a paid model API. Downloading requires a network, and the agent may process transcript text through a hosted service to summarize it; the entire workflow is not fully offline.
