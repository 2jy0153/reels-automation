"""LIBRARY 안의 기존 파일을 종류·날짜별 구조로 옮긴다.

- 영상 → LIBRARY/VIDEO/YYYY-MM-DD/
- 사진 → LIBRARY/PHOTO/YYYY-MM-DD/
- 둘 다 아닌 파일 → LIBRARY/_UNSORTED/ (날짜 분류 없이 한 폴더, 사용자가 직접 정리)
- 같은 이름·크기가 여러 개면 중복은 옮기지도 지우지도 않고 원래 자리에 둔다.
- 아무 파일도 삭제하지 않는다. 빈 폴더도 지우지 않는다.
- 같은 볼륨 안에서 이동(rename)하므로 파일 내용은 복사되지 않는다.
- 옮긴 기록은 CLIP_INDEX/move_log.json에 남겨 되돌릴 수 있게 한다.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ingest import destination, is_file_to_handle, unique_path

MOVE_LOG = "move_log.json"


@dataclass(frozen=True)
class Move:
    src: Path
    dst: Path  # dst == src 이면 옮기지 않는다
    note: str = ""


def _keeper_rank(path: Path, library: Path) -> int:
    """이미 자리 잡힌 파일(종류/날짜/이름 구조)을 먼저 보고, 중복이 생기면 그 쪽을 남긴다."""
    parts = path.relative_to(library).parts
    settled = (len(parts) == 3 and parts[0] in ("VIDEO", "PHOTO")) or (len(parts) == 2 and parts[0] == "_UNSORTED")
    return 0 if settled else 1


def plan_organize(library: Path, video_exts: list[str], photo_exts: list[str]) -> list[Move]:
    files = [p for p in library.rglob("*") if is_file_to_handle(p)]
    files.sort(key=lambda p: (_keeper_rank(p, library), str(p)))

    seen: dict[tuple[str, int], Path] = {}
    taken: set[Path] = set()
    moves: list[Move] = []
    for src in files:
        key = (src.name, src.stat().st_size)
        if key in seen:
            moves.append(Move(src, src, f"중복, 그대로 둠 (같은 파일: {seen[key].relative_to(library)})"))
            continue
        seen[key] = src

        target = destination(src, library, video_exts, photo_exts)
        if target == src:
            taken.add(target)
            moves.append(Move(src, src, "이미 제자리"))
            continue
        moves.append(Move(src, unique_path(target, taken)))
    return moves


def apply_organize(moves: list[Move], index_dir: Path) -> None:
    log_path = index_dir / MOVE_LOG
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    moved = 0
    for move in moves:
        if move.dst == move.src:
            continue
        move.dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(move.src, move.dst)
        log.append({"from": str(move.src), "to": str(move.dst)})
        moved += 1

    temp = log_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, log_path)
    print(f"정리 완료: 이동 {moved}개")
