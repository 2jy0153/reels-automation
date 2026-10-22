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

# 주제 색 목록 (규칙: reels/SUBTITLE_STYLE.md). 이름 → (hex, 주제)
COLORS = {
    "블루": ("#A6D9FF", "디지털"),
    "그린": ("#AEFFCA", "창업"),
    "오렌지": ("#FFB56E", "콘텐츠 제작"),
    "노랑": ("#FFEB6B", "템플릿 공유 등 이벤트"),
}


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


def _balanced_parts(text: str, parts: int, limit: int) -> list[str]:
    """글자 수가 비슷하도록 어절 경계에서 parts개 안팎으로 나눈다. 한 조각은 limit을 넘지 않는다."""
    return _split_long(text, min(limit, math.ceil(_length(text) / parts)))


def _fit_durations(items: list[tuple[float, float, str]], style: dict) -> list[tuple[float, float, str]]:
    """자막 하나를 min_seconds~max_seconds(기본 1~2초)에 맞춘다.
    2초를 넘으면 어절 경계에서 나누고, 1초보다 짧으면 같은 문단의 옆 블록과 합친다(글자 수와 2초 안에서만)."""
    limit = max_chars_per_cue(style)
    shortest = style.get("min_seconds", 1.0)
    longest = style.get("max_seconds", 2.0)
    split: list[tuple[float, float, str]] = []
    for start, end, text in items:
        parts = math.ceil((end - start) / longest - 1e-9)
        if parts > 1 and _length(text) > 1:
            pieces = _balanced_parts(text, parts, limit)
            split.extend((s, e, t) for (s, e), t in zip(timing.spread(pieces, start, end), pieces))
        else:
            split.append((start, end, text))
    merged: list[tuple[float, float, str]] = []
    for item in split:
        if merged and min(item[1] - item[0], merged[-1][1] - merged[-1][0]) < shortest:
            head = merged[-1]
            text = f"{head[2]} {item[2]}"
            if _length(text) <= limit and item[1] - head[0] <= longest:
                merged[-1] = (head[0], item[1], text)
                continue
        merged.append(item)
    return merged


def cues(timeline: list[dict], style: dict, wins: list[dict]) -> list[tuple[float, float, str]]:
    """문단의 자막 구간(말 시작 ~ 다음 말 시작 전)을 블록들에 글자 수 비율로 나눠 준다.
    블록 사이에 빈틈이 생기지 않는다. 쉼 시간은 앞 블록이 이어서 보여 준다.
    블록 길이는 1~2초에 맞춘다(_fit_durations)."""
    result = []
    for item, win in zip(timeline, wins):
        if item.get("subtitle"):
            # 말과 자막을 따로 정한 줄은 자막 칸을 쓴다. ' / '는 카드 나눔이라 카드끼리는 합치지 않는다.
            cards = [card.strip() for card in item["subtitle"].split(" / ") if card.strip()]
            for (start, end), card in zip(timing.spread(cards, *win["caption"]), cards):
                texts = _cue_texts(card, style)
                result.extend(_fit_durations(
                    [(s, e, t) for (s, e), t in zip(timing.spread(texts, start, end), texts)], style))
            continue
        texts = _cue_texts(item["narration"], style)
        line_cues = [(s, e, t) for (s, e), t in zip(timing.spread(texts, *win["caption"]), texts)]
        result.extend(_fit_durations(line_cues, style))
    return result


def build_srt(timeline: list[dict], style: dict, wins: list[dict]) -> str:
    """블록은 이미 한 줄 한계(max_chars) 안에 있으므로 줄을 다시 나누지 않는다. 두 줄은 프리미어에서 수동으로 맞춘다."""
    blocks = []
    for index, (start, end, text) in enumerate(cues(timeline, style, wins), start=1):
        blocks.append(f"{index}\n{format_time(start)} --> {format_time(end)}\n{text}\n")
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
