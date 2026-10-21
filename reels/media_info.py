"""영상의 방향(세로·가로)을 읽는다. 키프레임만 확인하므로 빠르고, Gemini를 쓰지 않는다.

영상 중간에 방향이 바뀌면 두 값을 모두 돌려준다. 예: ["세로", "가로"]
"""

import json
import subprocess
from pathlib import Path


def orientation_label(width: int, height: int, rotation: int) -> str:
    # 회전 정보가 90도 또는 270도면 가로와 세로가 바뀐 것으로 본다.
    if abs(rotation) % 180 == 90:
        width, height = height, width
    if width < height:
        return "세로"
    if width > height:
        return "가로"
    return "정방형"


def labels_from_frames(frames: list[dict]) -> list[str]:
    """ffprobe 키프레임 목록에서 나타난 방향을 순서대로, 중복 없이 모은다."""
    labels: list[str] = []
    for frame in frames:
        rotation = 0
        for side in frame.get("side_data_list", []):
            if "rotation" in side:
                rotation = int(round(float(side["rotation"])))
        label = orientation_label(int(frame["width"]), int(frame["height"]), rotation)
        if label not in labels:
            labels.append(label)
    return labels


def orientation_of(path: Path) -> list[str]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_frames",
         "-show_entries", "frame=width,height:frame_side_data_list=rotation", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    frames = json.loads(result.stdout or "{}").get("frames", [])
    return labels_from_frames(frames)


def stream_size(path: Path) -> tuple[int, int, int]:
    """파일에 저장된 가로·세로 크기와 회전 값(도). 회전 값이 있으면 재생 방향과 다르다."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    rotation = 0
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(round(float(side["rotation"])))
    if "rotate" in stream.get("tags", {}):
        rotation = int(stream["tags"]["rotate"])
    return int(stream["width"]), int(stream["height"]), rotation


def fill_scale(width: int, height: int, rotation: int, frame_width: int, frame_height: int) -> float:
    """화면을 꽉 채우는 확대율(%). 가운데를 기준으로 자르므로 넘치는 쪽은 잘린다."""
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return 100 * max(frame_width / width, frame_height / height)
