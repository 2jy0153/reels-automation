"""타임라인(timeline.json)으로 SRT 자막 파일을 만든다.

- 자막 문구는 대사 전체를 쓴다.
- 의미 단위(쉼표, 마침표, 물음표 등)로 나누고, 한 블록이 넘지 않도록 글자 수를 제한한다.
- 의미 단위가 한계를 넘으면 어절 경계에서 두 조각의 길이가 가장 비슷해지는 곳으로 나눈다.
- 글자 수 한계는 자막 디자인 설정(config.json의 subtitle)으로 계산한다. 디자인이 바뀌면 설정만 고친다.
"""

import json
import math
import re
from pathlib import Path

import timing

CLAUSE = re.compile(r"[^,.?!…]+[,.?!…]*")


def chars_per_line(style: dict) -> int:
    usable = style["frame_width"] - 2 * style["side_margin"]
    return math.floor(usable / (style["font_size"] * style["char_width_factor"]))


def max_chars_per_cue(style: dict) -> int:
    if "max_chars" in style:
        return style["max_chars"]
    return chars_per_line(style) * style["max_lines"]


def format_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _length(text: str) -> int:
    return len(text.replace(" ", ""))


def _split_long(text: str, limit: int) -> list[str]:
    """의미 단위 하나가 한계를 넘으면 어절 경계에서, 두 조각의 길이가 가장 비슷해지는 곳으로 나눈다."""
    parts = []
    while _length(text) > limit:
        words = text.split(" ")
        best, best_gap = 1, None
        for index in range(1, len(words)):
            left = " ".join(words[:index])
            if _length(left) > limit:
                break
            gap = abs(_length(left) - _length(" ".join(words[index:])))
            if best_gap is None or gap < best_gap:
                best, best_gap = index, gap
        parts.append(" ".join(words[:best]))
        text = " ".join(words[best:])
    if text:
        parts.append(text)
    return parts


def _clauses(narration: str, limit: int) -> list[str]:
    clauses = [c.strip() for c in CLAUSE.findall(narration) if c.strip()] or [narration.strip()]
    result = []
    for clause in clauses:
        result.extend(_split_long(clause, limit))
    return result


def _cue_texts(narration: str, style: dict) -> list[str]:
    """의미 단위 조각을 이어 붙여 블록을 만든다. 블록은 최대 글자 수를 넘지 않는다."""
    limit = max_chars_per_cue(style)
    cues: list[str] = []
    for clause in _clauses(narration, limit):
        if cues and _length(cues[-1]) + _length(clause) <= limit:
            cues[-1] = f"{cues[-1]} {clause}"
        else:
            cues.append(clause)
    return cues


def _wrap(text: str, width: int) -> list[str]:
    return _split_long(text, width)


def cues(timeline: list[dict], style: dict, wins: list[dict]) -> list[tuple[float, float, str]]:
    """문단의 자막 구간(말 시작 ~ 다음 말 시작 전)을 블록들에 글자 수 비율로 나눠 준다.
    블록 사이에 빈틈이 생기지 않는다. 쉼 시간은 앞 블록이 이어서 보여 준다."""
    result = []
    for item, win in zip(timeline, wins):
        texts = _cue_texts(item["narration"], style)
        for (start, end), text in zip(timing.spread(texts, *win["caption"]), texts):
            result.append((start, end, text))
    return result


def build_srt(timeline: list[dict], style: dict, wins: list[dict]) -> str:
    width = chars_per_line(style)
    blocks = []
    for index, (start, end, text) in enumerate(cues(timeline, style, wins), start=1):
        blocks.append(f"{index}\n{format_time(start)} --> {format_time(end)}\n" + "\n".join(_wrap(text, width)) + "\n")
    return "\n".join(blocks)


def load_timeline(voice_dir: Path) -> list[dict]:
    payload = json.loads((voice_dir / "timeline.json").read_text(encoding="utf-8"))
    return payload["lines"]


def manual_sheet(timeline: list[dict], style: dict, wins: list[dict]) -> str:
    """SRT를 가져올 수 없을 때 앱에 손으로 입력하는 목록."""
    lines = ["번호\t시작\t끝\t자막"]
    for index, (start, end, text) in enumerate(cues(timeline, style, wins), start=1):
        lines.append(f"{index}\t{format_time(start)}\t{format_time(end)}\t{text}")
    return "\n".join(lines) + "\n"
