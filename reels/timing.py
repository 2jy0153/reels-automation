"""음성의 실제 말 구간을 기준으로 영상과 자막의 시간을 나눈다.

- 말이 시작하는 시점(onset)은 음성 파일 앞부분의 무음 길이로 찾는다. 자막과 영상 전환은 이 시점에 맞춘다.
- 영상과 자막은 다음 문단의 말이 시작하기 전까지 이어진다. 쉼 구간에도 앞 화면과 앞 자막이 남는다.
- 문장 하나는 길이에 따라 영상 1~3개(약 4초마다 하나)를 쓴다.
"""

import math
import re
from pathlib import Path

import voice

SENTENCE = re.compile(r"[^.?!…]+[.?!…]+|[^.?!…]+$")
PIECE_SECONDS = 4.0
MAX_PIECES = 3
NOISE_DB = -35
EDGE_SILENCE = 0.05  # 파일 앞뒤에서 이 시간 이상 조용하면 말 시작·끝으로 본다


def length(text: str) -> int:
    return len(text.replace(" ", ""))


def sentences(narration: str) -> list[str]:
    found = [s.strip() for s in SENTENCE.findall(narration)]
    return [s for s in found if s] or [narration.strip()]


def piece_count(seconds: float) -> int:
    return min(MAX_PIECES, max(1, math.ceil(seconds / PIECE_SECONDS - 1e-9)))


def spread(texts: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """글자 수 비율로 시간을 나눈다. 구간들은 빈틈 없이 이어지고, 처음은 start, 끝은 end다."""
    total = sum(length(t) for t in texts) or 1
    spans, cursor, done = [], start, 0
    for index, text in enumerate(texts):
        done += length(text)
        nxt = end if index == len(texts) - 1 else start + (end - start) * done / total
        spans.append((cursor, nxt))
        cursor = nxt
    return spans


def sentence_spans(narration: str, start: float, end: float) -> list[tuple[float, float]]:
    return spread(sentences(narration), start, end)


def clip_count(narration: str, start: float, end: float) -> int:
    """이 문단에 필요한 영상 개수. 문장마다 1~3개씩 센다."""
    return sum(piece_count(e - s) for s, e in sentence_spans(narration, start, end))


def speech_bounds(path: Path) -> tuple[float, float]:
    """음성 파일 안에서 말이 시작하는 시점과 끝나는 시점(파일 시작 기준, 초)."""
    total = voice.duration(path)
    starts, ends = voice.silence_points(path, NOISE_DB, EDGE_SILENCE)
    onset = ends[0] if starts and ends and starts[0] <= EDGE_SILENCE else 0.0
    trailing = starts and (len(starts) > len(ends) or ends[-1] >= total - EDGE_SILENCE)
    speech_end = starts[-1] if trailing else total  # 파일 끝까지 이어진 무음은 말이 끝난 지점
    speech_end = min(max(speech_end, onset), total)
    return onset, speech_end


def windows(timeline: list[dict], bounds: list[tuple[float, float]]) -> list[dict]:
    """문단마다 영상 구간(video)과 자막 구간(caption)을 만든다. bounds는 문단별 (말 시작, 말 끝) 오프셋."""
    speech = []
    for line, (onset, speech_end) in zip(timeline, bounds):
        start_at = line["start"] + onset
        speech.append((start_at, max(start_at, line["start"] + speech_end)))
    result = []
    last = len(timeline) - 1
    for index, line in enumerate(timeline):
        start_at, end_at = speech[index]
        next_start = speech[index + 1][0] if index < last else None
        result.append({
            "no": line["no"],
            "video": (0.0 if index == 0 else start_at, next_start if next_start is not None else line["end"]),
            "caption": (start_at, next_start if next_start is not None else end_at),
        })
    return result


def windows_for(voice_dir: Path, timeline: list[dict]) -> list[dict]:
    bounds = [speech_bounds(voice_dir / f"{line['no']:02d}.mp3") for line in timeline]
    return windows(timeline, bounds)
