"""음성 타임라인과 편집 계획으로 프리미어 프로용 XML(xmeml)을 만든다.

입력
  voice/timeline.json   문단별 시작·끝 시간 (음성 기준)
  edit/plan.json        문단별로 쓸 영상 파일과 시작 지점 (in)

plan.json 형식
  [{"no": 1, "clip": "/경로/파일.mp4", "in": 0.0}, ...]

영상 조각은 문단의 말 시작부터 다음 문단의 말 시작 전까지 이어진다(쉼 포함). 빈틈이 없다.
마지막 문단은 음성이 끝나는 지점까지다.
"""

import json
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

FPS = 30
WIDTH = 1080
HEIGHT = 1920


def to_frames(seconds: float) -> int:
    return round(seconds * FPS)


def file_url(path: str) -> str:
    return "file://localhost" + quote(str(Path(path)))


def normalize_clips(entry: dict) -> list[dict]:
    """계획의 한 문단 항목을 영상 목록으로 바꾼다. 예전 형식(clip 하나)도 받는다."""
    if entry.get("clips"):
        return [{"clip": c["clip"] if isinstance(c, dict) else c,
                 "in": c.get("in") if isinstance(c, dict) else None} for c in entry["clips"]]
    if entry.get("clip"):
        return [{"clip": entry["clip"], "in": entry.get("in")}]
    return []


def video_pieces(timeline: list[dict], plan: list[dict], wins: list[dict],
                 clip_info: dict[str, dict]) -> tuple[list[dict], dict[int, int]]:
    """문단마다 문장 단위로 영상 조각(샷)을 만든다. 반환: (샷 목록, 영상을 다시 쓴 문단과 횟수)."""
    import shots as shots_mod
    import timing

    by_no = {item["no"]: item for item in plan}
    pieces: list[dict] = []
    repeated: dict[int, int] = {}
    for line, win in zip(timeline, wins):
        if line["no"] not in by_no:
            raise ValueError(f"{line['no']}번 문단이 편집 계획에 없습니다.")
        clips = []
        for choice in normalize_clips(by_no[line["no"]]):
            info = clip_info[choice["clip"]]
            clips.append({"clip": choice["clip"], "length": info["length"], "scores": info["scores"], "in": choice["in"]})
        spans = timing.sentence_spans(line["narration"], *win["video"])
        line_pieces, recycled = shots_mod.shots_for_spans(spans, clips)
        for piece in line_pieces:
            piece["no"] = line["no"]
        pieces.extend(line_pieces)
        if recycled:
            repeated[line["no"]] = recycled
    return pieces, repeated


def markers_for(timeline: list[dict], pieces: list[dict]) -> list[tuple[int, str]]:
    """영상 조각이 하나도 없는 문단마다 프리미어 마커를 찍는다."""
    covered = {piece["no"] for piece in pieces}
    return [(to_frames(line["start"]), f"{line['no']}번 문단: {line['narration'][:30]}")
            for line in timeline if line["no"] not in covered]


def scale_filter(percent: float) -> str:
    """프리미어 기본 모션 효과의 크기(Scale). 가운데를 기준으로 확대·축소한다."""
    return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid>"
            "<effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype>"
            '<parameter authoringApp="PremierePro"><parameterid>scale</parameterid><name>Scale</name>'
            f"<valuemin>0</valuemin><valuemax>1000</valuemax><value>{percent:.2f}</value></parameter>"
            "</effect></filter>")


def build_xmeml(name: str, timeline: list[dict], pieces: list[dict], narration_files: list[str],
                source_frames: dict[str, int], media: dict[str, dict] | None = None,
                width: int = 1080, height: int = 1920) -> str:
    """media: 영상 파일 경로 → {"width", "height", "scale"}. 없으면 화면 크기에 맞춘다고 보고 확대율 100%."""
    total_frames = to_frames(timeline[-1]["end"])
    file_ids: dict[str, str] = {}
    media = media or {}

    def file_block(path: str, frames: int, src_width: int, src_height: int, has_video: bool) -> str:
        fid = file_ids.setdefault(path, f"file-{len(file_ids) + 1}")
        video = (f"<video><samplecharacteristics><width>{src_width}</width><height>{src_height}</height>"
                 "</samplecharacteristics></video>") if has_video else ""
        audio = "<audio><channelcount>2</channelcount></audio>"
        return (f'<file id="{fid}"><name>{escape(Path(path).name)}</name>'
                f"<pathurl>{escape(file_url(path))}</pathurl>"
                f"<duration>{frames}</duration>"
                f"<media>{video}{audio}</media></file>")

    video_items = []
    for number, piece in enumerate(pieces, start=1):
        frames = source_frames[piece["clip"]]
        info = media.get(piece["clip"], {"width": width, "height": height, "scale": 100.0})
        video_items.append(
            f'<clipitem id="v{number}"><name>{escape(Path(piece["clip"]).name)}</name>'
            f"<duration>{frames}</duration><rate><timebase>{FPS}</timebase></rate>"
            f"<start>{to_frames(piece['timeline_start'])}</start>"
            f"<end>{to_frames(piece['timeline_end'])}</end>"
            f"<in>{to_frames(piece['source_in'])}</in>"
            f"<out>{to_frames(piece['source_out'])}</out>"
            f"{file_block(piece['clip'], frames, info['width'], info['height'], True)}"
            f"{scale_filter(info['scale'])}</clipitem>"
        )

    audio_items = []
    for number, (line, path) in enumerate(zip(timeline, narration_files), start=1):
        length = line["end"] - line["start"]
        audio_items.append(
            f'<clipitem id="a{number}"><name>{escape(Path(path).name)}</name>'
            f"<duration>{to_frames(length)}</duration><rate><timebase>{FPS}</timebase></rate>"
            f"<start>{to_frames(line['start'])}</start>"
            f"<end>{to_frames(line['end'])}</end>"
            f"<in>0</in><out>{to_frames(length)}</out>"
            f"{file_block(path, to_frames(length), 0, 0, False)}"
            "<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xmeml version="4"><sequence>'
        f"<name>{escape(name)}</name><duration>{total_frames}</duration>"
        f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
        "<media>"
        f"<video><format><samplecharacteristics><width>{width}</width><height>{height}</height>"
        f"<rate><timebase>{FPS}</timebase></rate></samplecharacteristics></format>"
        f"<track>{''.join(video_items)}</track></video>"
        f"<audio><track>{''.join(audio_items)}</track></audio>"
        "</media>"
        + "".join(f"<marker><name>{escape(text)}</name><in>{frame}</in><out>{frame}</out></marker>"
                  for frame, text in markers_for(timeline, pieces))
        + "</sequence></xmeml>\n"
    )


def load_plan(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
