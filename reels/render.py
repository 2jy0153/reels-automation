"""편집 계획, 나레이션, 자막으로 완성 영상(mp4)을 직접 만든다. 프리미어 없이 ffmpeg로 처리한다.

과정
1. 문단마다 영상 조각을 잘라 세로 1080×1920으로 맞춘다 (가로 영상은 가운데를 잘라서 쓴다).
2. 문단마다 나레이션을 그 문단의 길이(쉼 포함)에 맞춰 붙인다.
3. 조각과 음성을 순서대로 이어 붙이고, 자막(SRT)을 화면에 입힌다.

영상이 정해지지 않은 문단이 있으면 만들지 않고, 그 문단 번호를 알려 준다.
"""

import subprocess
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 30
SUBTITLE_STYLE = ("FontName=Apple SD Gothic Neo,FontSize=44,PrimaryColour=&H00FFFFFF,"
                  "OutlineColour=&H00000000,Outline=3,Alignment=2,MarginV=260")
SUBTITLE_NAME = "subtitles.srt"


def undecided_lines(plan: list[dict]) -> list[int]:
    return [item["no"] for item in plan if not item.get("clip")]


def segment_command(clip: str, start: float, length: float, out: Path) -> list[str]:
    """영상 조각 하나: 잘라서 세로로 맞추고, 소리는 뺀다."""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", clip, "-t", f"{length:.3f}",
        "-vf", f"scale=-2:{HEIGHT},crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ]


def narration_command(mp3: Path, length: float, out: Path) -> list[str]:
    """나레이션 하나: 그 문단 길이에 맞게 뒤를 무음으로 채운다."""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(mp3), "-af", "apad", "-t", f"{length:.3f}",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out),
    ]


def final_command(video: Path, audio: Path, subtitles_name: str, out: Path) -> list[str]:
    """이어 붙인 영상과 음성을 합치고, 자막을 입힌다. 자막 파일은 작업 폴더 안에 둔다."""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video), "-i", str(audio),
        "-vf", f"subtitles={subtitles_name}:force_style='{SUBTITLE_STYLE}'",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        str(out),
    ]


def render(plan: list[dict], timeline: list[dict], voice_dir: Path, srt: Path, out: Path) -> None:
    from assemble import video_pieces

    missing = undecided_lines(plan)
    if missing:
        raise RuntimeError(f"영상이 정해지지 않은 문단이 있습니다: {', '.join(f'{n}번' for n in missing)}")
    pieces = video_pieces(timeline, plan)
    work = out.parent / "_work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        segments, narrations = [], []
        for index, (line, piece) in enumerate(zip(timeline, pieces)):
            length = piece["timeline_end"] - piece["timeline_start"]
            segment = work / f"seg_{index:02d}.mp4"
            subprocess.run(segment_command(piece["clip"], piece["source_in"], length, segment), check=True)
            segments.append(segment)
            narration = work / f"nar_{index:02d}.wav"
            subprocess.run(narration_command(voice_dir / f"{line['no']:02d}.mp3", length, narration), check=True)
            narrations.append(narration)

        listing = work / "segments.txt"
        listing.write_text("".join(f"file '{segment.name}'\n" for segment in segments), encoding="utf-8")
        video = work / "joined.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", listing.name, "-c", "copy", video.name], cwd=work, check=True)

        audio_listing = work / "narrations.txt"
        audio_listing.write_text("".join(f"file '{n.name}'\n" for n in narrations), encoding="utf-8")
        audio = work / "joined.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", audio_listing.name, "-c", "copy", audio.name], cwd=work, check=True)

        (work / SUBTITLE_NAME).write_bytes(srt.read_bytes())
        subprocess.run(final_command(Path(video.name), Path(audio.name), SUBTITLE_NAME, out.resolve()),
                       cwd=work, check=True)
    finally:
        for leftover in work.glob("*"):
            leftover.unlink(missing_ok=True)
        work.rmdir()
