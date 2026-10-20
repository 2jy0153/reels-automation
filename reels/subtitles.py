"""타임라인(timeline.json)으로 SRT 자막 파일을 만든다. 자막 문구는 대사 전체를 쓴다."""

import json
import re
import textwrap
from pathlib import Path

LINE_WIDTH = 18  # 한 줄에 들어갈 대략적인 글자 수


def format_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


SENTENCE = re.compile(r"[^.?!]+[.?!]*")
MAX_CHARS_PER_CUE = LINE_WIDTH * 2  # 한 블록은 최대 2줄


def _chunks(narration: str) -> list[str]:
    """문장 단위로 나누고, 한 블록이 2줄을 넘지 않게 묶는다."""
    sentences = [s.strip() for s in SENTENCE.findall(narration) if s.strip()] or [narration.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        while len(sentence) > MAX_CHARS_PER_CUE:  # 한 문장이 너무 길면 공백 기준으로 쪼갠다
            cut = sentence.rfind(" ", 0, MAX_CHARS_PER_CUE)
            cut = cut if cut > 0 else MAX_CHARS_PER_CUE
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= MAX_CHARS_PER_CUE:
            chunks[-1] = f"{chunks[-1]} {sentence}"
        else:
            chunks.append(sentence)
    return chunks


def cues(timeline: list[dict]) -> list[tuple[float, float, str]]:
    """문단의 말하는 시간(시작~끝)을 블록들에 글자 수 비율로 나눠 준다. 쉼 시간은 블록에 넣지 않는다."""
    result = []
    for item in timeline:
        chunks = _chunks(item["narration"])
        total_chars = sum(len(chunk.replace(" ", "")) for chunk in chunks) or 1
        cursor = item["start"]
        for index, chunk in enumerate(chunks):
            share = len(chunk.replace(" ", "")) / total_chars
            end = item["end"] if index == len(chunks) - 1 else cursor + (item["end"] - item["start"]) * share
            result.append((cursor, end, chunk))
            cursor = end
    return result


def build_srt(timeline: list[dict]) -> str:
    blocks = []
    for index, (start, end, text) in enumerate(cues(timeline), start=1):
        lines = textwrap.wrap(text, width=LINE_WIDTH) or [text]
        blocks.append(f"{index}\n{format_time(start)} --> {format_time(end)}\n" + "\n".join(lines) + "\n")
    return "\n".join(blocks)


def load_timeline(voice_dir: Path) -> list[dict]:
    payload = json.loads((voice_dir / "timeline.json").read_text(encoding="utf-8"))
    return payload["lines"]
