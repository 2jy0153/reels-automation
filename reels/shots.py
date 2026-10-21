"""한 문단의 시간을 영상 조각(샷)으로 나눈다.

- 문단의 자막 블록(의미 단위)을 영상 개수만큼 묶는다. 영상이 블록보다 많으면 블록마다 하나.
- 각 묶음 안에서 영상을 순서대로 쓴다. 영상이 짧으면 남은 시간은 다음 영상으로 이어 붙인다.
- 영상의 시작 지점은 흔들림이 가장 적은 구간으로 고른다. 사용자가 시작 지점을 적었으면 그 값을 쓴다.
"""

import motion


def group_cues(spans: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    """자막 블록 구간들을 count개 묶음으로 묶는다. 묶음 경계는 항상 블록 경계다."""
    if count >= len(spans):
        return list(spans)
    total = spans[-1][1] - spans[0][0]
    groups: list[tuple[float, float]] = []
    group_start = spans[0][0]
    for index, (start, end) in enumerate(spans):
        made = len(groups) + 1
        boundary = spans[0][0] + total * made / count
        is_last_span = index == len(spans) - 1
        if made < count and end >= boundary and not is_last_span:
            groups.append((group_start, end))
            group_start = end
    groups.append((group_start, spans[-1][1]))
    return groups


def shots_for_line(line_start: float, line_end: float, cue_spans: list[tuple[float, float]],
                   clips: list[dict]) -> tuple[list[dict], float]:
    """
    clips: [{"clip": 경로, "length": 초, "scores": 초별 흔들림 점수, "in": 직접 지정한 시작 또는 None}, ...]
    반환: (샷 목록, 영상이 모자라서 비워진 시간)
    """
    if not clips:
        return [], line_end - line_start
    groups = group_cues(cue_spans or [(line_start, line_end)], len(clips))
    queue = [dict(clip, offset=None) for clip in clips]
    shots: list[dict] = []
    missing = 0.0
    for group_start, group_end in groups:
        now = group_start
        while now < group_end - 1e-6:
            if not queue:
                missing += group_end - now
                break
            current = queue[0]
            available = current["length"] - (current["offset"] or 0.0)
            if available <= 1e-6:
                queue.pop(0)
                continue
            need = min(group_end - now, available)
            if current["offset"] is None:
                current["offset"] = (current["in"] if current.get("in") is not None
                                     else motion.best_start(current["scores"], need))
            source_in = current["offset"]
            shots.append({
                "clip": current["clip"],
                "timeline_start": round(now, 3),
                "timeline_end": round(now + need, 3),
                "source_in": round(source_in, 3),
                "source_out": round(source_in + need, 3),
            })
            current["offset"] += need
            now += need
            if current["length"] - current["offset"] <= 1e-6:
                queue.pop(0)
        # 이 묶음에서 쓰던 영상은 다음 묶음으로 넘어가면서 넘긴다. 짧은 영상이 묶음 안에서 모자랄 때만 이어 붙인다.
        if queue and queue[0]["offset"] is not None:
            queue.pop(0)
    return shots, missing
