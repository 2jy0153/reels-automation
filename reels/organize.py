"""LIBRARY 안의 기존 원본을 날짜별 구조(LIBRARY/YYYY-MM-DD/)로 정리한다.

- 하위 폴더(BTS, PRODUCT, VIDEO 등)를 없애고 모든 영상을 날짜 폴더 한 단계로 모은다.
- 같은 이름·크기가 여러 개면 한 개만 남기고 나머지는 DUPLICATES로 옮긴다.
- 이미 날짜 폴더 안에 있는 파일이 남는 쪽이 된다.
- 같은 볼륨 안에서 이동(rename)하므로 파일 내용은 복사되지 않는다.
- 옮긴 기록은 CLIP_INDEX/move_log.json에 남겨 되돌릴 수 있게 한다.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ingest import is_video, new_name, recording_date, unique_path

DATE_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}")
MOVE_LOG = "move_log.json"


@dataclass(frozen=True)
class Move:
    src: Path
    dst: Path | None  # None이면 중복이라 DUPLICATES로 옮긴다
    note: str = ""


def _in_date_folder(path: Path, library: Path) -> bool:
    return path.parent.parent == library and bool(DATE_FOLDER.fullmatch(path.parent.name))


def plan_organize(library: Path, exts: list[str]) -> list[Move]:
    files = [p for p in library.rglob("*") if is_video(p, exts)]
    # 날짜 폴더 안의 파일을 먼저 두어, 중복이 생기면 이미 제자리에 있는 쪽을 남긴다.
    files.sort(key=lambda p: (not _in_date_folder(p, library), str(p)))

    seen: dict[tuple[str, int], Path] = {}
    taken: set[Path] = set()
    moves: list[Move] = []
    for src in files:
        key = (src.name, src.stat().st_size)
        if key in seen:
            moves.append(Move(src, None, f"같은 이름·크기 파일이 있음: {seen[key].relative_to(library)}"))
            continue
        seen[key] = src

        when = recording_date(src)
        target = library / f"{when:%Y-%m-%d}" / new_name(src, when)
        if target == src:
            taken.add(target)
            moves.append(Move(src, src, "이미 제자리"))
            continue
        moves.append(Move(src, unique_path(target, taken)))
    return moves


def _remove_empty_folders(library: Path) -> int:
    removed = 0
    # 깊은 폴더부터 지워야 상위 폴더도 비게 된다.
    for folder in sorted((p for p in library.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if DATE_FOLDER.fullmatch(folder.name) and folder.parent == library:
            continue  # 날짜 폴더는 비어 있어도 남긴다.
        try:
            folder.rmdir()
            removed += 1
        except OSError:
            pass  # 비어 있지 않은 폴더(영상 아닌 파일 포함)는 그대로 둔다.
    return removed


def apply_organize(moves: list[Move], library: Path, duplicates: Path, index_dir: Path) -> None:
    log_path = index_dir / MOVE_LOG
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    moved = dup = 0
    for move in moves:
        if move.dst == move.src:
            continue
        if move.dst is None:
            target = unique_path(duplicates / move.src.name, set())
            shutil.move(str(move.src), target)
            dup += 1
            continue
        move.dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(move.src, move.dst)
        log.append({"from": str(move.src), "to": str(move.dst)})
        moved += 1

    temp = log_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, log_path)
    removed = _remove_empty_folders(library)
    print(f"정리 완료: 이동 {moved}개, 중복 이동 {dup}개, 빈 폴더 삭제 {removed}개")
