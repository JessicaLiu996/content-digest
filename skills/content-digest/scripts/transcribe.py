#!/usr/bin/env python3
"""Download one public episode/video, transcribe locally, remove task media."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

OUTPUT_ROOT = Path.cwd() / "content-digest-results"
MODEL = Path(os.environ["CONTENT_DIGEST_MODEL"]).expanduser() if os.environ.get("CONTENT_DIGEST_MODEL") else None
OWNER = "long-media-digest-v1"


def save_json(path, value):
    path = Path(path)
    draft = path.with_suffix(path.suffix + ".part")
    draft.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    draft.replace(path)


def timestamp(seconds, srt=False):
    ms = max(0, round(float(seconds) * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    base = f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{base},{ms:03}" if srt else base


def source_key(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS Apple Podcasts episode or YouTube video URL without embedded credentials.")
    query = parse_qs(parsed.query)
    if host == "podcasts.apple.com":
        episode = query.get("i", [""])[0]
        if not episode.isdigit():
            raise ValueError("Provide an Apple Podcasts episode URL containing an i= episode ID, not a show page.")
        return "apple-" + episode
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
        video = query.get("v", [""])[0]
        parts = parsed.path.strip("/").split("/")
        if host.endswith("youtu.be"):
            video = parts[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            video = parts[1]
        if re.fullmatch(r"[\w-]{11}", video, flags=re.ASCII):
            return "youtube-" + video
        raise ValueError("Provide one YouTube video URL, not a channel or playlist.")
    raise ValueError("Only Apple Podcasts episodes and YouTube videos are supported.")


def clean_stale(root):
    """Only remove our marked, unlocked job directories. Never follow symlinks."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    removed = []
    for path in root.glob("job-*"):
        if path.is_symlink() or not path.is_dir():
            continue
        marker, lock = path / "owner.json", path / "lock"
        if marker.is_symlink() or lock.is_symlink():
            continue
        try:
            if json.loads(marker.read_text()).get("owner") != OWNER:
                continue
            with lock.open("a+") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(path)
                removed.append(str(path))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return removed


class JobSpace:
    def __init__(self, root):
        self.root = Path(root)
        self.path = None
        self.lock = None

    def __enter__(self):
        clean_stale(self.root)
        self.path = Path(tempfile.mkdtemp(prefix="job-", dir=self.root))
        self.lock = (self.path / "lock").open("a+")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        save_json(self.path / "owner.json", {"owner": OWNER})
        return self

    def __exit__(self, *exc):
        try:
            if self.path is not None:
                shutil.rmtree(self.path)
        finally:
            if self.lock:
                self.lock.close()

    def run(self, command, name, timeout=None):
        log = self.path / (name + ".log")
        with log.open("wb") as out:
            proc = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True, pass_fds=(self.lock.fileno(),))
            try:
                code = proc.wait(timeout=timeout)
            except BaseException:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise
        if code:
            tail = log.read_text(errors="replace")[-3500:]
            raise RuntimeError(f"{name} failed (exit code {code}):\n{tail}")
        return log.read_text(errors="replace")


def chunk_windows(duration, size, overlap=2.0):
    for index in range(math.ceil(duration / size)):
        start, end = index * size, min((index + 1) * size, duration)
        yield index, start, end, max(0, start - overlap), min(duration, end + overlap)


def whisper_segments(document, offset=0.0):
    result = []
    for row in document.get("transcription", []):
        text = row.get("text", "").strip()
        times = row.get("offsets", {})
        if text and "from" in times and "to" in times:
            result.append({"start": offset + times["from"] / 1000,
                           "end": offset + times["to"] / 1000, "text": text})
    return result


def merge_segments(chunks):
    """Keep unique boundary text despite timing drift between independent decodes.

    Only collapse identical text overlapping in adjacent chunks. Ambiguous edge
    variants remain visible rather than silently losing a sentence.
    """
    segments = []
    previous = {}
    for _start, _end, rows in chunks:
        current = {}
        for row in rows:
            key = re.sub(r"\W", "", row["text"]).casefold()
            duplicate = next((prev for prev in previous.get(key, [])
                              if key and row["start"] < prev["end"]
                              and prev["start"] < row["end"]), None)
            if duplicate is not None:
                previous[key].remove(duplicate)
                duplicate["start"] = min(duplicate["start"], row["start"])
                duplicate["end"] = max(duplicate["end"], row["end"])
                kept = duplicate
            else:
                kept = dict(row)
                segments.append(kept)
            current.setdefault(key, []).append(kept)
        previous = current
    return sorted(segments, key=lambda row: row["start"])


def summary_parts(segments, limit=9000):
    parts, rows, size = [], [], 0
    for segment in segments:
        row = f'[{timestamp(segment["start"])}–{timestamp(segment["end"])}] {segment["text"]}'
        if rows and size + len(row) > limit:
            parts.append(rows)
            rows, size = [], 0
        rows.append(row)
        size += len(row) + 1
    if rows:
        parts.append(rows)
    return parts


@lru_cache(maxsize=1)
def chinese_converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def normalize_chinese_text(meta, segments):
    """Convert Chinese orthography without translating or changing timing."""
    languages = meta.get('detected_languages') or [meta.get('language_requested', 'auto')]
    if not any(lang == 'auto' or lang.lower().startswith('zh') for lang in languages):
        return meta, segments
    convert = chinese_converter().convert
    converted_meta = dict(meta, text_normalization='OpenCC t2s')
    for field in ('title', 'series'):
        if isinstance(meta.get(field), str):
            converted_meta[field] = convert(meta[field])
    return converted_meta, [dict(row, text=convert(row['text'])) for row in segments]


def export_text(result_dir, meta, segments, duration, complete):
    meta, segments = normalize_chinese_text(meta, segments)
    result_dir = Path(result_dir)
    header = [f'# {meta["title"]}', "", f'Source URL: {meta["source_url"]}',
              f'Processed duration: {timestamp(duration)}',
              'Text source: local Whisper speech recognition; not manually checked sentence by sentence.',
              'Coverage: ' + ('The full audio was processed; this does not guarantee word-for-word accuracy.' if complete else 'Test excerpt only, not the full transcript.'),
              'Preserves spoken content and filler words. Chinese characters are normalized to Simplified Chinese; no content is inferred from descriptions.', ""]
    lines = [f'[{timestamp(s["start"])}–{timestamp(s["end"])}] {s["text"]}' for s in segments]
    paragraphs, group = [], []
    def flush_group():
        if group:
            paragraphs.append(f'[{timestamp(group[0]["start"])}–{timestamp(group[-1]["end"])}]\n' +
                              " ".join(row["text"] for row in group))
            group.clear()
    for row in segments:
        if group and (row["start"] - group[-1]["end"] > 4 or
                      row["end"] - group[0]["start"] > 45 or
                      sum(len(item["text"]) for item in group) + len(row["text"]) > 250):
            flush_group()
        group.append(row)
    flush_group()
    (result_dir / "transcript.md").write_text("\n".join(header) + "\n\n" + "\n\n".join(paragraphs) + "\n")
    (result_dir / "transcript.txt").write_text("\n".join(lines) + "\n")
    srt = [f'{i}\n{timestamp(s["start"], True)} --> {timestamp(s["end"], True)}\n{s["text"]}\n'
           for i, s in enumerate(segments, 1)]
    (result_dir / "transcript.srt").write_text("\n".join(srt))
    save_json(result_dir / "transcript.json", {"metadata": meta, "segments": segments})
    parts = summary_parts(segments)
    index, first = [], 1
    for number, rows in enumerate(parts, 1):
        index.append({"part": number, "file": "transcript.txt", "start_line": first,
                      "end_line": first + len(rows) - 1, "characters": sum(map(len, rows))})
        first += len(rows)
    save_json(result_dir / "reading-index.json", index)
    return index


def quality_notes(segments, duration):
    warnings = []
    cursor = 0.0
    for row in segments:
        if row["start"] - cursor > 30:
            warnings.append(f'{timestamp(cursor)}–{timestamp(row["start"])} has no recognized text; this may be silence, music, or missed speech. Check the source.')
        if cursor - row["start"] > .5:
            warnings.append(f'{timestamp(row["start"])} has overlapping recognition intervals; possible boundary duplicates or alternative decodes are retained for review.')
        cursor = max(cursor, row["end"])
    if duration - cursor > 30:
        warnings.append(f'{timestamp(cursor)}–{timestamp(duration)} has no recognized text at the end; check the source.')
    for a, b, c in zip(segments, segments[1:], segments[2:]):
        if a["text"] == b["text"] == c["text"]:
            warnings.append(f'{timestamp(a["start"])} has repeated recognition output; review it.')
    return list(dict.fromkeys(warnings))


def dependency_check(model):
    missing = [name for name in ("ffmpeg", "ffprobe", "whisper-cli", "node") if not shutil.which(name)]
    if missing:
        raise RuntimeError("Missing local tools: " + ", ".join(missing))
    if not model.is_file():
        raise RuntimeError(f"Whisper model not found: {model}")
    try:
        import yt_dlp  # noqa: F401
        from opencc import OpenCC  # noqa: F401
    except ImportError:
        raise RuntimeError("Run with the configured Python environment and install the Skill requirements.txt dependencies.") from None


def execute(args):
    clean_stale(args.work_root)
    key = source_key(args.url)
    if args.model is None:
        raise ValueError("Provide --model PATH or set CONTENT_DIGEST_MODEL to a whisper.cpp GGML model.")
    model = args.model.expanduser().resolve()
    dependency_check(model)
    if not 30 <= args.chunk_seconds <= 1800:
        raise ValueError("Chunk size must be between 30 and 1800 seconds.")
    if args.limit_seconds is not None and args.limit_seconds <= 0:
        raise ValueError("Sample duration must be positive.")
    result_dir = args.output.resolve() / key
    if result_dir.exists() and any(result_dir.iterdir()):
        result_dir = args.output.resolve() / f'{key}-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}'
    result_dir.mkdir(parents=True, exist_ok=True)
    state = {"source_url": args.url, "status": "running", "audio_cleanup": "pending",
             "summary_status": "pending", "result_dir": str(result_dir), "stages": []}
    save_json(result_dir / "task-state.json", state)
    started = time.monotonic()
    try:
        with JobSpace(args.work_root) as job:
            base = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                    "--no-cache-dir", "--js-runtimes", "node", "--socket-timeout", "25",
                    "--retries", "2", "--fragment-retries", "2"]
            if args.cookies_from_browser:
                base += ["--cookies-from-browser", args.cookies_from_browser]
            print("Reading episode metadata...", flush=True)
            raw = job.run(base + ["--skip-download", "--dump-single-json", "--quiet", args.url], "metadata", 180)
            # Warnings can share the log stream; select the JSON object line.
            info = next((json.loads(line) for line in raw.splitlines() if line.startswith('{"id"')), None)
            if info is None:
                for line in reversed(raw.splitlines()):
                    if line.startswith("{"):
                        with contextlib.suppress(json.JSONDecodeError):
                            info = json.loads(line)
                            break
            if not info or not info.get("id"):
                raise RuntimeError("Could not retrieve episode metadata.")
            if str(info["id"]) != key.split("-", 1)[1]:
                raise RuntimeError("Resolved episode ID does not match the requested source; stopping.")
            if info.get("is_live"):
                raise RuntimeError("Live streams are not supported; use an available recording.")
            meta = {"source_url": args.url, "id": info["id"], "title": info.get("title", key),
                    "series": info.get("series") or info.get("channel"), "source_duration": info.get("duration"),
                    "model": model.name, "language_requested": args.language,
                    "source_type": "local_asr",
                    "pipeline": "yt-dlp audio -> whisper.cpp -> agent summary"}
            state.update(metadata=meta)
            save_json(result_dir / "task-state.json", state)
            print(f'Downloading audio: {meta["title"]}', flush=True)
            download = base + ["--quiet", "--no-progress", "-f", "bestaudio/best",
                               "-o", str(job.path / "source.%(ext)s")]
            if args.limit_seconds:
                download += ["--download-sections", f"*0-{args.limit_seconds}"]
            job.run(download + [args.url], "download")
            audio_files = [p for p in job.path.glob("source.*") if p.suffix not in {".part", ".ytdl"}]
            if len(audio_files) != 1:
                raise RuntimeError("Expected one complete downloaded audio file.")
            audio = audio_files[0]
            probe = json.loads(job.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", str(audio)], "probe", 60))
            duration = float(probe["format"]["duration"])
            source_duration = float(info.get("duration") or duration)
            complete = args.limit_seconds is None
            if complete and duration < source_duration - max(5.0, source_duration * .01):
                raise RuntimeError(f"Audio appears incomplete: downloaded {duration:.1f}s, source reports {source_duration:.1f}s.")
            total = math.ceil(duration / args.chunk_seconds)
            chunks, detected_languages = [], []
            for index, start, end, window_start, window_end in chunk_windows(duration, args.chunk_seconds):
                wav = job.path / "chunk.wav"
                prefix = job.path / f"chunk-{index:03}"
                job.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", str(window_start), "-i", str(audio),
                         "-t", str(window_end-window_start), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], "convert", 180)
                print(f'Transcribing {index+1}/{total}: {timestamp(start)}–{timestamp(end)}', flush=True)
                command = ["whisper-cli", "-m", str(model), "-f", str(wav), "-l", args.language,
                           "-oj", "-of", str(prefix), "-t", str(args.threads)]
                if args.no_gpu:
                    command.append("-ng")
                job.run(command, f"whisper-{index:03}")
                document = json.loads(prefix.with_suffix(".json").read_text())
                rows = whisper_segments(document, window_start)
                chunks.append((start, end, rows))
                language = document.get("result", {}).get("language")
                if language:
                    detected_languages.append(language)
                state["stages"].append({"chunk": index+1, "start": start, "end": end, "segments": len(rows)})
                save_json(result_dir / "task-state.json", state)
                wav.unlink(missing_ok=True)
                prefix.with_suffix(".json").unlink(missing_ok=True)
            segments = merge_segments(chunks)
            if not segments:
                raise RuntimeError("Transcription returned no text; an empty result is not a complete transcript.")
            for row in segments:
                row["start"] = max(0.0, row["start"])
                row["end"] = min(duration, row["end"])
            meta["detected_languages"] = sorted(set(detected_languages))
            meta, segments = normalize_chinese_text(meta, segments)
            parts = export_text(result_dir, meta, segments, duration, complete)
            warnings = quality_notes(segments, duration)
            state.update(status="transcribed" if complete else "sample_transcribed", metadata=meta,
                         audio_duration=duration, processed_seconds=duration,
                         segments=len(segments), text_characters=sum(len(s["text"]) for s in segments),
                         summary_parts=parts, warnings=warnings)
            (result_dir / "recognition-notes.md").write_text(
                "# Recognition notes\n\nAll planned chunks were processed; time coverage does not guarantee transcription accuracy.\n\n" +
                ("\n".join("- " + w for w in warnings) if warnings else "No text gaps over 30 seconds or three identical consecutive segments detected. Names, numbers, and terminology still need review.") + "\n")
    except BaseException as exc:
        state.update(status="cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed",
                     error=str(exc) or type(exc).__name__)
        raise
    finally:
        state["audio_cleanup"] = "complete" if not ('job' in locals() and job.path and job.path.exists()) else "failed"
        state["elapsed_seconds"] = round(time.monotonic()-started, 1)
        save_json(result_dir / "task-state.json", state)
    print(json.dumps({"status": state["status"], "result_dir": str(result_dir),
                      "summary_parts": state.get("summary_parts", []), "audio_cleanup": state["audio_cleanup"]}, ensure_ascii=False), flush=True)
    return result_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--work-root", type=Path, default=OUTPUT_ROOT / ".work")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--language", default="auto", help="Whisper language code, e.g. auto, zh, en")
    parser.add_argument("--chunk-seconds", type=int, default=600)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--limit-seconds", type=float, help="Test excerpt only; output is marked as a sample, not a complete transcript")
    parser.add_argument("--cookies-from-browser", help="Use only with explicit user permission to read browser login state")
    parser.add_argument("--clean-only", action="store_true")
    args = parser.parse_args()
    if args.clean_only:
        print(json.dumps(clean_stale(args.work_root), ensure_ascii=False))
        return
    if not args.url:
        parser.error("An episode or video URL is required.")
    def stop(signum, frame):
        raise KeyboardInterrupt(f"Received stop signal {signum}")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        execute(args)
    except KeyboardInterrupt:
        print("Task stopped; temporary-file cleanup was attempted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
