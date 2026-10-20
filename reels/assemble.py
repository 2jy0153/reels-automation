"""음성 타임라인과 편집 계획으로 프리미어 프로용 XML(xmeml)을 만든다.

입력
  voice/timeline.json   문단별 시작·끝 시간 (음성 기준)
  edit/plan.json        문단별로 쓸 영상 파일과 시작 지점 (in)

plan.json 형식
  [{"no": 1, "clip": "/경로/파일.mp4", "in": 0.0}, ...]

영상 조각은 해당 문단의 시작부터 다음 문단이 시작하기 전까지(쉼 포함) 이어진다.
마지막 문단은 음성이 끝나는 지점까지다.
"""

import json
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

FPS = 30


def to_frames(seconds: float) -> int:
    return round(seconds * FPS)


def file_url(path: str) -> str:
    return "file://localhost" + quote(str(Path(path)))


def video_pieces(timeline: list[dict], plan: list[dict]) -> list[dict]:
    """영상이 정해진 문단마다 영상 조각의 타임라인 위치와 소스 구간을 계산한다.
    영상이 아직 없는 문단은 조각을 만들지 않는다."""
    by_no = {item["no"]: item for item in plan}
    for line in timeline:
        if line["no"] not in by_no:
            raise ValueError(f"{line['no']}번 문단이 편집 계획에 없습니다.")
    pieces = []
    for index, line in enumerate(timeline):
        entry = by_no[line["no"]]
        if not entry.get("clip"):
            continue
        start = line["start"]
        following = timeline[index + 1] if index + 1 < len(timeline) else None
        has_next_clip = following is not None and by_no[following["no"]].get("clip")
        end = following["start"] if has_next_clip else line["end"]
        pieces.append({
            "no": line["no"],
            "clip": entry["clip"],
            "timeline_start": start,
            "timeline_end": end,
            "source_in": float(entry.get("in", 0.0)),
            "source_out": float(entry.get("in", 0.0)) + (end - start),
        })
    return pieces


def markers_for(timeline: list[dict], plan: list[dict]) -> list[tuple[int, str]]:
    """영상이 없는 문단마다 프리미어 마커를 찍는다."""
    empty = {item["no"] for item in plan if not item.get("clip")}
    return [(to_frames(line["start"]), f"{line['no']}번 문단: {line['narration'][:30]}")
            for line in timeline if line["no"] in empty]


def build_xmeml(name: str, timeline: list[dict], plan: list[dict], narration_files: list[str],
                source_frames: dict[str, int], width: int = 1080, height: int = 1920) -> str:
    pieces = video_pieces(timeline, plan)
    total_frames = to_frames(timeline[-1]["end"])
    file_ids: dict[str, str] = {}

    def file_block(path: str, frames: int, has_video: bool) -> str:
        fid = file_ids.setdefault(path, f"file-{len(file_ids) + 1}")
        media = ("<video><samplecharacteristics><width>%d</width><height>%d</height></samplecharacteristics></video>"
                 % (width, height)) if has_video else ""
        audio = "<audio><channelcount>2</channelcount></audio>"
        return (f'<file id="{fid}"><name>{escape(Path(path).name)}</name>'
                f"<pathurl>{escape(file_url(path))}</pathurl>"
                f"<duration>{frames}</duration>"
                f"<media>{media}{audio}</media></file>")

    video_items = []
    for number, piece in enumerate(pieces, start=1):
        frames = source_frames[piece["clip"]]
        video_items.append(
            f'<clipitem id="v{number}"><name>{escape(Path(piece["clip"]).name)}</name>'
            f"<duration>{frames}</duration><rate><timebase>{FPS}</timebase></rate>"
            f"<start>{to_frames(piece['timeline_start'])}</start>"
            f"<end>{to_frames(piece['timeline_end'])}</end>"
            f"<in>{to_frames(piece['source_in'])}</in>"
            f"<out>{to_frames(piece['source_out'])}</out>"
            f"{file_block(piece['clip'], frames, True)}</clipitem>"
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
            f"{file_block(path, to_frames(length), False)}"
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
                  for frame, text in markers_for(timeline, plan))
        + "</sequence></xmeml>\n"
    )


def load_plan(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
