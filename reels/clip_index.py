"""클립 인덱스(CLIP_INDEX/clips.json)와 태그별 색인(tag_index.json)을 관리한다."""

import json
import os
from datetime import datetime
from pathlib import Path


def load_clips(index_dir: Path) -> dict:
    path = index_dir / "clips.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: object) -> None:
    # 임시 파일에 먼저 쓰고 교체해서, 쓰는 도중 실패해도 기존 파일이 깨지지 않게 한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def upsert_clip(index_dir: Path, clip_id: str, record: dict) -> None:
    clips = load_clips(index_dir)
    previous = {k: v for k, v in clips.get(clip_id, {}).items() if k != "error"}
    record = {**previous, **record, "updated_at": datetime.now().isoformat(timespec="seconds")}
    clips[clip_id] = record
    _write_json(index_dir / "clips.json", clips)
    _write_json(index_dir / "tag_index.json", build_tag_index(clips))


def build_tag_index(clips: dict) -> dict:
    """태그 값 → 클립 ID 목록. 검토가 필요한 클립은 별도 목록으로 모은다."""
    index: dict[str, set[str]] = {}
    for clip_id, clip in clips.items():
        tags = {clip.get("bag_type", "미확인"), clip.get("person", "미확인")}
        if clip.get("needs_review"):
            tags.add("검토필요")
        for tag in tags:
            index.setdefault(tag, set()).add(clip_id)
    return {tag: sorted(ids) for tag, ids in sorted(index.items())}
