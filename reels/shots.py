"""문장 구간을 영상 조각(샷)으로 나눈다.

- 문장 길이에 따라 영상 1~3개를 쓴다 (timing.piece_count). 조각 하나에는 영상 하나를 쓴다.
- 영상이 조각보다 짧으면 남은 시간은 다음 영상으로 이어 붙인다.
- 영상이 모자라면 마지막으로 쓴 영상의 원본을 더 길게 쓴다. 속도는 바꾸지 않고, 같은 원본의 이어지는 부분을 쓴다.
- 영상의 시작 지점은 흔들림이 가장 적은 구간으로 고른다. 사용자가 시작 지점을 적었으면 그 값을 쓴다.
"""

import motion
import timing

EPS = 1e-6


def shots_for_spans(spans: list[tuple[float, float]], clips: list[dict]) -> tuple[list[dict], int, float]:
    """
    spans: 문장마다 (시작, 끝)
    clips: [{"clip": 경로, "length": 초, "scores": 초별 흔들림 점수, "in": 직접 지정한 시작 또는 None}, ...]
    반환: (샷 목록, 원본을 길게 쓴 횟수, 영상이 끝까지 모자라서 비워진 시간(초))
    """
    queue = [dict(clip, offset=None) for clip in clips if clip["length"] > EPS]
    shots: list[dict] = []
    extended = 0
    lacking = 0.0
    for start, end in spans:
        if end - start <= EPS:
            continue
        count = timing.piece_count(end - start)
        step = (end - start) / count
        now = start
        for piece in range(count):
            piece_end = end if piece == count - 1 else now + step
            used, missing = _piece(queue, now, piece_end, shots)
            extended += used
            lacking += missing
            now = piece_end
    return shots, extended, lacking


def _extend(shot: dict, end: float) -> float:
    """샷을 end까지 늘린다. 원본을 더 길게 쓰므로 속도는 그대로다. 원본이 모자라면 못 채운 시간을 돌려준다."""
    room = shot["length"] - shot["source_out"]
    extra = min(end - shot["timeline_end"], room)
    if extra > EPS:
        shot["source_out"] = round(shot["source_out"] + extra, 3)
        shot["timeline_end"] = round(shot["timeline_end"] + extra, 3)
    return max(0.0, end - shot["timeline_end"])


def _piece(queue: list[dict], start: float, end: float, shots: list[dict]) -> tuple[int, float]:
    """한 조각을 채운다. 영상 하나를 쓰고, 모자라면 다음 영상으로 이어 간다.
    쓸 영상이 없으면 앞 샷을 늘린다. 반환: (늘린 횟수, 못 채운 시간)."""
    now = start
    while now < end - EPS:
        if not queue:
            if not shots:
                return 0, end - now  # 쓸 영상이 하나도 없는 문단
            before = shots[-1]["timeline_end"]
            missing = _extend(shots[-1], end)
            return (1 if shots[-1]["timeline_end"] > before + EPS else 0), missing
        current = queue[0]
        if current["offset"] is None:
            given = current.get("in")
            if given is not None and given < current["length"]:
                current["offset"] = given
            else:
                current["offset"] = motion.best_start(current["scores"], end - now)
        available = current["length"] - current["offset"]
        if available <= EPS:
            queue.pop(0)
            continue
        need = min(end - now, available)
        shots.append({
            "clip": current["clip"],
            "length": current["length"],
            "timeline_start": round(now, 3),
            "timeline_end": round(now + need, 3),
            "source_in": round(current["offset"], 3),
            "source_out": round(current["offset"] + need, 3),
        })
        current["offset"] += need
        now += need
        if current["length"] - current["offset"] <= EPS:
            queue.pop(0)
    # 이 조각에서 쓴 영상은 남은 부분이 있어도 다음 조각에서는 새 영상을 쓴다.
    if queue and queue[0]["offset"] is not None:
        queue.pop(0)
    return 0, 0.0
