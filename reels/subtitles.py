"""타임라인(timeline.json)으로 SRT 자막 파일을 만든다. 자막 문구는 대사 전체를 쓴다."""

import json
import textwrap
from pathlib import Path

LINE_WIDTH = 18  # 한 줄에 들어갈 대략적인 글자 수


def format_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(timeline: list[dict]) -> str:
    blocks = []
    for index, item in enumerate(timeline, start=1):
        text = "\n".join(textwrap.wrap(item["narration"], width=LINE_WIDTH)) or item["narration"]
        blocks.append(f"{index}\n{format_time(item['start'])} --> {format_time(item['end'])}\n{text}\n")
    return "\n".join(blocks)


def load_timeline(voice_dir: Path) -> list[dict]:
    payload = json.loads((voice_dir / "timeline.json").read_text(encoding="utf-8"))
    return payload["lines"]
