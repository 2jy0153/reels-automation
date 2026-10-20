"""대본 줄마다 ElevenLabs로 나레이션을 만들고, 배속과 쉼을 반영한 타임라인을 만든다.

REELS/<ID>/voice/
  raw/NN.mp3      ElevenLabs가 만든 원본 음성
  NN.mp3          배속을 적용한 최종 음성 (줄 번호 두 자리)
  timeline.json   배속과 줄별 실제 길이, 쉼, 시작·끝 시간 (음성 길이 기준)
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
TIMELINE = "timeline.json"


def synthesize(text: str, voice_id: str, model: str, api_key: str) -> bytes:
    body = json.dumps({"text": text, "model_id": model}).encode("utf-8")
    request = urllib.request.Request(
        ELEVEN_URL.format(voice_id=voice_id),
        data=body,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read()[:200].decode("utf-8", "replace")
        raise RuntimeError(f"ElevenLabs 요청 실패 ({error.code}): {detail}") from error


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def speed_command(src: Path, dst: Path, factor: float) -> list[str]:
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", f"atempo={factor}", str(dst)]


def apply_speed(src: Path, dst: Path, factor: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if factor == 1.0:
        shutil.copyfile(src, dst)
        return
    temp = dst.parent / f".{dst.name}.partial.mp3"
    try:
        subprocess.run(speed_command(src, temp, factor), check=True)
        os.replace(temp, dst)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def pause_after(narration: str, pause: float, pause_after_question: float) -> float:
    """질문으로 끝나는 줄 뒤에는 조금 더 쉰다."""
    return pause_after_question if narration.strip().endswith("?") else pause


def build_timeline(lines: list[dict], durations: list[float], pause: float, pause_after_question: float) -> list[dict]:
    """실제 음성 길이로 타임라인을 만든다. 목표 시간은 쓰지 않는다."""
    timeline = []
    cursor = 0.0
    for index, (line, length) in enumerate(zip(lines, durations)):
        start = round(cursor, 3)
        end = round(start + length, 3)
        gap = 0.0
        if index < len(lines) - 1:
            gap = pause_after(line["narration"], pause, pause_after_question)
        timeline.append({
            "no": line["no"],
            "start": start,
            "end": end,
            "duration": round(length, 3),
            "pause_after": gap,
            "narration": line["narration"],
        })
        cursor = end + gap
    return timeline


def write_timeline(voice_dir: Path, speed: float, timeline: list[dict]) -> None:
    payload = {"speed": speed, "lines": timeline}
    temp = voice_dir / f".{TIMELINE}.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, voice_dir / TIMELINE)


SILENCE_DB = -35
SILENCE_SECONDS = 0.3


def detect_silences(path: Path, noise_db: int = SILENCE_DB, min_silence: float = SILENCE_SECONDS) -> list[tuple[float, float]]:
    """ffmpeg의 silencedetect로 무음 구간 (시작, 끝) 목록을 찾는다."""
    import re

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    starts = [float(value) for value in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    return list(zip(starts, ends))  # 끝까지 이어진 무음은 끝이 없어 제외된다


def choose_cuts(silences: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    """문단 수에서 한 개 적은 수만큼, 가장 긴 무음 구간을 자를 자리로 고른다."""
    needed = count - 1
    if len(silences) < needed:
        raise ValueError(f"무음 구간이 {len(silences)}개뿐이라 {count}개 문단으로 나눌 수 없습니다. "
                         "문단 사이 쉼을 늘려 다시 만들거나 자르는 자리를 직접 정해 주세요.")
    longest = sorted(silences, key=lambda s: s[1] - s[0], reverse=True)[:needed]
    return sorted(longest)


def segments_from_cuts(total: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    segments = []
    previous_end = 0.0
    for cut_start, cut_end in cuts:
        segments.append((previous_end, cut_start))
        previous_end = cut_end
    segments.append((previous_end, total))
    return segments


def cut_audio(src: Path, dst: Path, start: float, end: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.parent / f".{dst.name}.partial.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(temp)],
            check=True,
        )
        os.replace(temp, dst)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
