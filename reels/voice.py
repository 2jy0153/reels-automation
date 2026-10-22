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
            "subtitle": line.get("subtitle"),
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


def cut_targets(total: float, char_counts: list[int]) -> list[float]:
    """문단 글자 수 비율에 맞춰, 각 문단 경계가 있어야 할 시간."""
    chars = sum(char_counts)
    targets, cumulative = [], 0
    for count in char_counts[:-1]:
        cumulative += count
        targets.append(total * cumulative / chars)
    return targets


def choose_cuts_by_text(silences: list[tuple[float, float]], total: float,
                        char_counts: list[int]) -> list[tuple[float, float]]:
    """글자 수 비율에 가장 가까운 무음 구간을 문단 수만큼 - 1 개 고른다. 순서는 지킨다."""
    needed = len(char_counts) - 1
    if needed == 0:
        return []
    if len(silences) < needed:
        raise ValueError(f"무음 구간이 {len(silences)}개뿐이라 {len(char_counts)}개 문단으로 나눌 수 없습니다. "
                         "문단 사이 쉼을 늘려 다시 만들거나 자르는 자리를 직접 정해 주세요.")
    targets = cut_targets(total, char_counts)
    mids = [(start + end) / 2 for start, end in silences]
    m = len(silences)
    inf = float("inf")
    # dp[j]: 지금까지 고른 경계 수만큼 골랐고 마지막 경계가 j번 무음일 때의 최소 오차
    dp = [abs(mids[j] - targets[0]) for j in range(m)]
    back: list[list[int | None]] = [[None] * m]
    for step in range(1, needed):
        new = [inf] * m
        pointer: list[int | None] = [None] * m
        best, best_index = inf, None
        for j in range(m):
            if best < inf:
                new[j] = best + abs(mids[j] - targets[step])
                pointer[j] = best_index
            if dp[j] < best:
                best, best_index = dp[j], j
        dp = new
        back.append(pointer)
    last = min(range(m), key=lambda j: dp[j])
    chosen = [last]
    for step in range(needed - 1, 0, -1):
        last = back[step][last]
        chosen.append(last)
    return [silences[j] for j in sorted(chosen)]


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


def silence_points(path: Path, noise_db: int, min_silence: float) -> tuple[list[float], list[float]]:
    """무음의 시작 시점 목록과 끝 시점 목록. 파일 끝까지 이어지는 무음은 끝 시점이 없다."""
    import re

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    starts = [float(value) for value in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    return starts, ends
