"""타임라인(timeline.json)으로 SRT 자막 파일을 만든다.

- 자막 문구는 대사 전체를 쓴다.
- 우선순위는 문장 끝 > 의미 단위 > 글자 수 한계 > 1~2초다. 1~2초는 목표일 뿐이라 시간 때문에 문장이나 구를 쪼개지 않는다.
- 문장 끝(. ? ! …)에서는 반드시 끊고, 한 문장이 한계 이하이면 나누지 않는다.
- 한계를 넘는 문장만 쉼표 → 연결어미(~면, ~서, ~고 …) → 어절 균형 순서로 나눈다.
- 자막 경계는 글자 수 비율이 아니라 문장 음성 안의 실제 쉼(무음) 위치에 맞춘다(없을 때만 글자 수 비율).
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


# 이 어미로 끝나는 어절 뒤는 의미가 끊기는 자리라 나누기 좋다.
CONNECTIVE = re.compile(r"(면|서|고|데|니까|지만|대신|때|도록|라|며)$")
# 이 어절 앞에서는 나누지 않는다 (앞 어절에 붙는 의존 어절).
STICKY_NEXT = re.compile(r"^(않|못|안|건|게|거|수|것|때문|뿐|만큼|듯|따름)")


def _split_long(text: str, limit: int) -> list[str]:
    """의미 단위 하나가 한계를 넘으면 어절 경계에서 나눈다.
    연결어미 뒤는 우선하고, 의존 어절(않으면, 건, 게 …) 앞은 피한다. 그 안에서 두 조각의 길이가 비슷한 곳을 고른다."""
    parts = []
    while _length(text) > limit:
        words = text.split(" ")
        best, best_score = 1, None
        for index in range(1, len(words)):
            left = " ".join(words[:index])
            if _length(left) > limit:
                break
            score = abs(_length(left) - _length(" ".join(words[index:])))
            if CONNECTIVE.search(words[index - 1]):
                score -= 6
            if STICKY_NEXT.match(words[index]):
                score += 12
            if best_score is None or score < best_score:
                best, best_score = index, score
        parts.append(" ".join(words[:best]))
        text = " ".join(words[best:])
    if text:
        parts.append(text)
    return parts


SENTENCE = re.compile(r"[^.?!…]+[.?!…]*")
SENTENCE_END = re.compile(r"[.?!…]$")


def _clauses(narration: str, limit: int) -> list[str]:
    clauses = [c.strip() for c in CLAUSE.findall(narration) if c.strip()] or [narration.strip()]
    result = []
    for clause in clauses:
        result.extend(_split_long(clause, limit))
    return result


def _cue_texts(narration: str, style: dict) -> list[str]:
    """문장 끝에서는 반드시 끊고, 문장 안에서는 쉼표 단위로 묶는다.
    한 문장이 한계 이하이면 나누지 않는다. 한계를 넘을 때만 쉼표, 연결어미, 어절 순으로 나눈다."""
    limit = max_chars_per_cue(style)
    cues: list[str] = []
    for sentence in (x.strip() for x in SENTENCE.findall(narration) if x.strip()):
        if _length(sentence) <= limit:
            cues.append(sentence)
            continue
        group: list[str] = []
        for clause in (c.strip() for c in CLAUSE.findall(sentence) if c.strip()):
            pieces = _split_long(clause, limit)
            if len(pieces) > 1 and group:
                cues.extend(group)
                group = []
            for piece in pieces:
                if group and len(pieces) == 1 and _length(group[-1]) + _length(piece) <= limit:
                    group[-1] = f"{group[-1]} {piece}"
                else:
                    group.append(piece)
        cues.extend(group)
    return cues


def _wrap(text: str, width: int) -> list[str]:
    return _split_long(text, width)


def _balanced_parts(text: str, parts: int, limit: int) -> list[str]:
    """글자 수가 비슷하도록 어절 경계에서 parts개 안팎으로 나눈다. 한 조각은 limit을 넘지 않는다."""
    return _split_long(text, min(limit, math.ceil(_length(text) / parts)))


def _fit_durations(items: list[tuple[float, float, str]], style: dict) -> list[tuple[float, float, str]]:
    """읽기 쉬운 문장·의미 단위가 우선이다. 길다고 나누지 않는다(1~2초는 목표일 뿐).
    1초보다 짧은 블록은 같은 문장 안의 앞 블록(문장 끝으로 끝나지 않은 것)과 합친다. 글자 수 한계 안에서만."""
    limit = max_chars_per_cue(style)
    shortest = style.get("min_seconds", 1.0)
    merged: list[tuple[float, float, str]] = []
    for item in items:
        if merged and (item[1] - item[0] < shortest or merged[-1][1] - merged[-1][0] < shortest):
            head = merged[-1]
            text = f"{head[2]} {item[2]}"
            if not SENTENCE_END.search(head[2]) and _length(text) <= limit:
                merged[-1] = (head[0], item[1], text)
                continue
        merged.append(item)
    return merged


def snap_to_silences(spans: list[tuple[float, float]], silences: list[float], span: tuple[float, float],
                     tolerance: float = 0.2, minimum: float = 0.3) -> list[tuple[float, float]]:
    """글자 수 비율로 나눈 경계를 실제 음성의 쉼(무음 가운데) 위치로 옮긴다.
    경계마다 span 길이의 tolerance 비율 안에서 가장 가까운 쉼을 찾고, 없으면 그대로 둔다. 구간은 계속 이어진다."""
    if len(spans) < 2 or not silences:
        return spans
    reach = (span[1] - span[0]) * tolerance
    bounds = [spans[0][0]] + [end for _, end in spans[:-1]]
    new_bounds = [bounds[0]]
    for target in bounds[1:]:
        near = [m for m in silences if abs(m - target) <= reach and m > new_bounds[-1] + minimum]
        new_bounds.append(min(near, key=lambda m: abs(m - target)) if near else target)
    new_bounds.append(spans[-1][1])
    return [(a, b) for a, b in zip(new_bounds, new_bounds[1:])]


def cues(timeline: list[dict], style: dict, wins: list[dict],
         silences: dict[int, list[float]] | None = None) -> list[tuple[float, float, str]]:
    """줄의 자막 구간(말 시작 ~ 다음 말 시작 전)을 블록들에 나눠 준다.
    블록 사이에 빈틈이 생기지 않는다. 쉼 시간은 앞 블록이 이어서 보여 준다.
    silences가 있으면(줄 번호 → 문장 음성 안의 쉼 위치, 타임라인 기준 초) 경계를 그 위치에 맞추고,
    없거나 쉼이 없는 경계만 글자 수 비율로 둔다."""
    result = []
    for item, win in zip(timeline, wins):
        found = (silences or {}).get(item["no"], [])
        if item.get("subtitle"):
            # 말과 자막을 따로 정한 줄은 자막 칸을 쓴다. ' / '는 카드 나눔이라 카드끼리는 합치지 않는다.
            cards = [card.strip() for card in item["subtitle"].split(" / ") if card.strip()]
            card_spans = snap_to_silences(timing.spread(cards, *win["caption"]), found, win["caption"])
            for (start, end), card in zip(card_spans, cards):
                texts = _cue_texts(card, style)
                spans = snap_to_silences(timing.spread(texts, start, end), found, (start, end))
                result.extend(_fit_durations([(s, e, t) for (s, e), t in zip(spans, texts)], style))
            continue
        texts = _cue_texts(item["narration"], style)
        spans = snap_to_silences(timing.spread(texts, *win["caption"]), found, win["caption"])
        result.extend(_fit_durations([(s, e, t) for (s, e), t in zip(spans, texts)], style))
    return result


def build_srt(timeline: list[dict], style: dict, wins: list[dict],
              silences: dict[int, list[float]] | None = None) -> str:
    """블록은 이미 한 줄 한계(max_chars) 안에 있으므로 줄을 다시 나누지 않는다. 두 줄은 프리미어에서 수동으로 맞춘다."""
    blocks = []
    for index, (start, end, text) in enumerate(cues(timeline, style, wins, silences), start=1):
        blocks.append(f"{index}\n{format_time(start)} --> {format_time(end)}\n{text}\n")
    return "\n".join(blocks)


def load_timeline(voice_dir: Path) -> list[dict]:
    """자막용 타임라인. 문장 단위 타임라인('sentences')이 있으면 그것을, 없으면 문단 단위('lines')를 쓴다."""
    payload = json.loads((voice_dir / "timeline.json").read_text(encoding="utf-8"))
    return payload.get("sentences") or payload["lines"]


def manual_sheet(timeline: list[dict], style: dict, wins: list[dict]) -> str:
    """SRT를 가져올 수 없을 때 앱에 손으로 입력하는 목록."""
    lines = ["번호\t시작\t끝\t자막"]
    for index, (start, end, text) in enumerate(cues(timeline, style, wins), start=1):
        lines.append(f"{index}\t{format_time(start)}\t{format_time(end)}\t{text}")
    return "\n".join(lines) + "\n"
