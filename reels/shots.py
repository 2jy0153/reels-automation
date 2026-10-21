"""문장 구간을 영상 조각(샷)으로 나눈다.

- 문장 길이에 따라 영상 1~3개를 쓴다 (timing.piece_count). 조각 하나에는 영상 하나를 쓴다.
- 영상이 조각보다 짧으면 남은 시간은 다음 영상으로 이어 붙인다.
- 문단의 영상이 모자라면 같은 영상을 다시 쓰지 않는다. 앞 영상을 끝점까지 늘린다(느리게 재생).
- 영상의 시작 지점은 흔들림이 가장 적은 구간으로 고른다. 사용자가 시작 지점을 적었으면 그 값을 쓴다.
"""

import motion
import timing

EPS = 1e-6


def shots_for_spans(spans: list[tuple[float, float]], clips: list[dict]) -> tuple[list[dict], int]:
    """
    spans: 문장마다 (시작, 끝)
    clips: [{"clip": 경로, "length": 초, "scores": 초별 흔들림 점수, "in": 직접 지정한 시작 또는 None}, ...]
    반환: (샷 목록, 영상이 모자라서 앞 영상을 늘린 횟수)
    샷의 speed는 재생 속도 배율이다. 1.0이면 원래 속도, 0.5면 절반 속도(두 배 길게).
    """
    queue = [dict(clip, offset=None) for clip in clips if clip["length"] > EPS]
    shots: list[dict] = []
    stretched = 0
    for start, end in spans:
        if end - start <= EPS:
            continue
        count = timing.piece_count(end - start)
        step = (end - start) / count
        now = start
        for piece in range(count):
            piece_end = end if piece == count - 1 else now + step
            stretched += _piece(queue, now, piece_end, shots)
            now = piece_end
    return shots, stretched


def _stretch(shot: dict, end: float) -> None:
    """샷의 끝점을 end까지 늘린다. 원본 구간은 그대로이고 재생 속도만 낮아진다."""
    source_length = shot["source_out"] - shot["source_in"]
    shot["timeline_end"] = round(end, 3)
    shot["speed"] = round(source_length / (end - shot["timeline_start"]), 4)


def _piece(queue: list[dict], start: float, end: float, shots: list[dict]) -> int:
    """한 조각을 채운다. 영상 하나를 쓰고, 모자라면 다음 영상으로 이어 간다.
    다음 영상이 없으면 앞 샷을 늘린다. 늘린 횟수(0 또는 1)를 돌려준다."""
    now = start
    stretched = 0
    while now < end - EPS:
        if not queue:
            if not shots:
                break  # 쓸 영상이 하나도 없는 문단
            _stretch(shots[-1], end)
            stretched += 1
            break
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
            "speed": 1.0,
        })
        current["offset"] += need
        now += need
        if current["length"] - current["offset"] <= EPS:
            queue.pop(0)
    # 이 조각에서 쓴 영상은 남은 부분이 있어도 다음 조각에서는 새 영상을 쓴다.
    if queue and queue[0]["offset"] is not None:
        queue.pop(0)
    return stretched
