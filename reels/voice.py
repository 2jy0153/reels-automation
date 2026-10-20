"""대본 줄마다 ElevenLabs로 나레이션을 만들고, 배속과 쉼을 반영한 타임라인을 만든다.

REELS/<ID>/voice/
  raw/NN.mp3      ElevenLabs가 만든 원본 음성
  NN.mp3          배속을 적용한 최종 음성 (줄 번호 두 자리)
  timeline.json   줄별 길이, 쉼, 시작·끝 시간
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
            "target_start": line["target_start"],
            "target_end": line["target_end"],
            "start": start,
            "end": end,
            "duration": round(length, 3),
            "target_duration": line["target_end"] - line["target_start"],
            "pause_after": gap,
            "narration": line["narration"],
        })
        cursor = end + gap
    return timeline


def write_timeline(voice_dir: Path, timeline: list[dict]) -> None:
    temp = voice_dir / f".{TIMELINE}.tmp"
    temp.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, voice_dir / TIMELINE)
