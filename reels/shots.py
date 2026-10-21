"""문장 구간을 영상 조각(샷)으로 나눈다.

- 문장 길이에 따라 영상 1~3개를 쓴다 (timing.piece_count). 조각 하나에는 영상 하나를 쓴다.
- 영상이 조각보다 짧으면 남은 시간은 다음 영상으로 이어 붙인다.
- 영상의 시작 지점은 흔들림이 가장 적은 구간으로 고른다. 사용자가 시작 지점을 적었으면 그 값을 쓴다.
- 문단의 영상이 모자라면 처음부터 다시 쓴다. 몇 번 다시 썼는지 돌려줘서 계획에 영상을 더 넣도록 알린다.
"""

import motion
import timing

EPS = 1e-6


def shots_for_spans(spans: list[tuple[float, float]], clips: list[dict]) -> tuple[list[dict], int]:
    """
    spans: 문장마다 (시작, 끝)
    clips: [{"clip": 경로, "length": 초, "scores": 초별 흔들림 점수, "in": 직접 지정한 시작 또는 None}, ...]
    반환: (샷 목록, 영상을 처음부터 다시 쓴 횟수)
    """
    base = [dict(clip, offset=None) for clip in clips if clip["length"] > EPS]
    if not base:
        return [], 0
    queue = [dict(clip) for clip in base]
    recycled = 0

    def refill() -> None:
        nonlocal recycled
        if not queue:
            recycled += 1
            queue.extend(dict(clip, offset=None) for clip in base)

    shots: list[dict] = []
    for start, end in spans:
        if end - start <= EPS:
            continue
        count = timing.piece_count(end - start)
        step = (end - start) / count
        now = start
        for piece in range(count):
            piece_end = end if piece == count - 1 else now + step
            _piece(queue, refill, now, piece_end, shots)
            now = piece_end
    return shots, recycled


def _piece(queue: list[dict], refill, start: float, end: float, shots: list[dict]) -> None:
    """한 조각을 채운다. 영상 하나를 쓰고, 모자라면 다음 영상으로 이어 간다."""
    now = start
    while now < end - EPS:
        if not queue:
            refill()
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
