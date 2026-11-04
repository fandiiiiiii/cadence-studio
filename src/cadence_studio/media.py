"""Audio probing, safe ingest, compression and demo asset generation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, BinaryIO

from .config import TMP_DIR

ALLOWED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
    ".aif",
    ".aiff",
    ".mp4",
    ".webm",
}
MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class MediaError(RuntimeError):
    pass


def configure_tools(ffmpeg_path: str | None = None, ffprobe_path: str | None = None) -> None:
    global FFMPEG, FFPROBE
    if ffmpeg_path:
        FFMPEG = ffmpeg_path
    if ffprobe_path:
        FFPROBE = ffprobe_path


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=flags,
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_sha256(path: Path) -> str:
    """Hash used for dedupe; tolerant of a missing file in imported bundles."""
    return sha256_file(path) if path.exists() else ""


def probe_audio(path: Path) -> dict[str, Any]:
    if FFPROBE:
        result = _run(
            [
                FFPROBE,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=30,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                fmt = payload.get("format", {})
                audio_stream = next(
                    (s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), {}
                )
                duration = float(fmt.get("duration") or audio_stream.get("duration") or 0)
                return {
                    "duration_sec": round(duration, 3) if duration else None,
                    "sample_rate": int(audio_stream["sample_rate"]) if audio_stream.get("sample_rate") else None,
                    "channels": int(audio_stream["channels"]) if audio_stream.get("channels") else None,
                    "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
                    "codec": audio_stream.get("codec_name", ""),
                    "container": fmt.get("format_name", ""),
                }
            except (ValueError, KeyError, json.JSONDecodeError):
                pass
    return _probe_with_mutagen(path)


def _probe_with_mutagen(path: Path) -> dict[str, Any]:
    try:
        from mutagen import File as MutagenFile  # type: ignore

        audio = MutagenFile(path)
        if audio is not None:
            info = getattr(audio, "info", None)
            return {
                "duration_sec": round(float(info.length), 3) if info and getattr(info, "length", None) else None,
                "sample_rate": int(getattr(info, "sample_rate", 0)) or None,
                "channels": int(getattr(info, "channels", 0)) or None,
                "bitrate": int(getattr(info, "bitrate", 0)) or None,
                "codec": "",
                "container": "",
            }
    except Exception:  # noqa: BLE001
        pass
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                return {
                    "duration_sec": round(frames / rate, 3) if rate else None,
                    "sample_rate": rate,
                    "channels": wav.getnchannels(),
                    "bitrate": rate * wav.getnchannels() * wav.getsampwidth() * 8,
                    "codec": "pcm_s16le",
                    "container": "wav",
                }
        except (wave.Error, OSError):
            pass
    return {
        "duration_sec": None,
        "sample_rate": None,
        "channels": None,
        "bitrate": None,
        "codec": "",
        "container": "",
    }


def safe_filename(name: str) -> str:
    name = Path(name or "audio").name
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).strip(" .")
    if not name:
        name = "audio.mp3"
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".mp3"
    return f"{stem[:160]}{ext}"


def save_stream_to_file(stream: BinaryIO, target: Path, max_bytes: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with target.open("wb") as out:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise MediaError(f"文件超过大小限制（{max_bytes // (1024 * 1024)} MB）")
            out.write(chunk)
    if total == 0:
        target.unlink(missing_ok=True)
        raise MediaError("上传文件为空")
    return total


def prepare_inference_audio(
    source: Path,
    target: Path,
    *,
    bitrate: str = "96k",
    max_seconds: int = 1200,
) -> Path:
    """Create a compact, broadly compatible upload copy; never modifies the original."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if FFMPEG:
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TMP_DIR), delete=False) as handle:
            tmp = Path(handle.name)
        try:
            result = _run(
                [
                    FFMPEG,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-t",
                    str(max_seconds),
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    bitrate,
                    str(tmp),
                ],
                timeout=180,
            )
            if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                raise MediaError(f"音频转码失败：{result.stderr[-300:] or '未知错误'}")
            os.replace(tmp, target)
            return target
        finally:
            tmp.unlink(missing_ok=True)
    # Without ffmpeg, send the original if it is already a supported container.
    shutil.copy2(source, target)
    return target


def generate_demo_audio(target: Path, *, variant: int = 0, seconds: int = 28) -> None:
    """Generate an original, royalty-free ambient loop for first-run demos."""
    target.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22050
    variants = [
        (196.00, [1.0, 1.25, 1.5, 2.0], 0.22),
        (146.83, [1.0, 1.189, 1.498, 2.0], 0.18),
        (174.61, [1.0, 1.335, 1.5, 2.0], 0.2),
        (220.00, [1.0, 1.2, 1.5, 1.8], 0.16),
    ]
    root, ratios, tempo = variants[variant % len(variants)]
    beat = 60 / (72 + variant * 6)
    frames = []
    total = sample_rate * seconds
    for index in range(total):
        t = index / sample_rate
        envelope = min(1.0, t / 1.8) * min(1.0, (seconds - t) / 2.2)
        pad = sum(
            math.sin(2 * math.pi * root * ratio * t + variant * 0.4) / (idx + 2)
            for idx, ratio in enumerate(ratios)
        ) * 0.28
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * t / beat)
        bass = math.sin(2 * math.pi * root * 0.5 * t) * 0.16 * (0.55 + 0.45 * pulse)
        shimmer = math.sin(2 * math.pi * root * 4.0 * t) * 0.025 * (0.5 + 0.5 * math.sin(2 * math.pi * t / 7))
        sample = (pad + bass + shimmer) * envelope
        sample = max(-0.95, min(0.95, sample))
        frames.append(struct.pack("<h", int(sample * 32767)))
    raw = b"".join(frames)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(raw)
    if FFMPEG:
        mp3 = target.with_suffix(".mp3")
        result = _run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(target),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(mp3),
            ],
            timeout=60,
        )
        if result.returncode == 0 and mp3.exists():
            target.unlink(missing_ok=True)
            os.replace(mp3, target.with_suffix(".mp3"))


def audio_tech_note(probe: dict[str, Any]) -> str:
    duration = probe.get("duration_sec")
    if not duration:
        return "音频时长未知"
    return f"{duration / 60:.1f} 分钟 · {probe.get('sample_rate') or '?'} Hz · {probe.get('channels') or '?'} 声道"


def delete_tree(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
