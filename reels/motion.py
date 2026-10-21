"""영상의 흔들림을 1초 단위 점수로 재고, 덜 흔들린 구간을 고른다.

점수: 인접한 프레임 사이의 화면 변화량 평균. 값이 클수록 많이 움직였다는 뜻이다.
Gemini를 쓰지 않는다. 결과는 CLIP_INDEX/motion.json에 저장해서 같은 영상은 한 번만 잰다.
"""

import json
import math
import os
import subprocess
from pathlib import Path

WIDTH, HEIGHT, FPS = 160, 90, 5
CACHE_NAME = "motion.json"


def motion_per_second(path: Path) -> list[float]:
    frame_size = WIDTH * HEIGHT
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    frames = [data[i:i + frame_size] for i in range(0, len(data) - frame_size + 1, frame_size)]
    changes = [
        sum(abs(x - y) for x, y in zip(a, b)) / frame_size
        for a, b in zip(frames, frames[1:])
    ]
    return [
        sum(changes[i:i + FPS]) / len(changes[i:i + FPS])
        for i in range(0, len(changes), FPS)
    ]


def best_start(scores: list[float], need: float) -> float:
    """need초 길이 구간 중 흔들림 평균이 가장 낮은 시작 지점(초). 영상이 짧으면 0."""
    window = max(1, math.ceil(need))
    if window > len(scores):
        return 0.0
    best_index, best_value = 0, None
    for start in range(len(scores) - window + 1):
        value = sum(scores[start:start + window]) / window
        if best_value is None or value < best_value:
            best_index, best_value = start, value
    return float(best_index)


def cached_scores(path: Path, cache_dir: Path) -> list[float]:
    cache_path = cache_dir / CACHE_NAME
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    key = str(path)
    if key not in cache:
        cache[key] = motion_per_second(path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, cache_path)
    return cache[key]
