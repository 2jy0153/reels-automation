"""INBOX의 파일을 LIBRARY 안의 알맞은 자리로 옮긴다.

- 영상 → LIBRARY/VIDEO/YYYY-MM-DD/YYYYMMDD_원래이름.확장자
- 사진 → LIBRARY/PHOTO/YYYY-MM-DD/YYYYMMDD_원래이름.확장자
- 둘 다 아닌 파일 → LIBRARY/_UNSORTED/원래이름 (날짜 분류 없이 한 폴더)
- 날짜: 파일명에 YYYYMMDD가 있으면 그 날짜, 없으면 파일 수정일
- 중복: 원본 이름과 크기가 같으면 먼저 들어온 한 개만 남기고 DUPLICATES로 뺀다
- 원본은 복사본의 크기가 같다고 확인된 뒤에만 INBOX에서 지운다
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
SEPARATORS = re.compile(r"[_\-\s]+")
LOG_NAME = "ingest_log.json"
VIDEO = "VIDEO"
PHOTO = "PHOTO"
UNSORTED = "_UNSORTED"


@dataclass(frozen=True)
class Plan:
    src: Path
    dst: Path | None  # None이면 중복이라 DUPLICATES로 옮긴다
    note: str = ""


def is_file_to_handle(path: Path) -> bool:
    # macOS 메타데이터(._로 시작)와 .DS_Store는 제외한다.
    return path.is_file() and not path.name.startswith(".")


def kind(path: Path, video_exts: list[str], photo_exts: list[str]) -> str:
    ext = path.suffix.lower()
    if ext in video_exts:
        return VIDEO
    if ext in photo_exts:
        return PHOTO
    return UNSORTED


def find_name_date(stem: str) -> tuple[date, tuple[int, int]] | None:
    """파일 이름 안의 촬영일(YYYYMMDD)과 그 위치를 찾는다. 예: A001_09222312 는 날짜가 아니다."""
    for match in DATE_PATTERN.finditer(stem):
        year, month, day = map(int, match.groups())
        try:
            return date(year, month, day), match.span()
        except ValueError:
            continue
    return None


def recording_date(path: Path) -> date:
    found = find_name_date(path.stem)
    if found:
        return found[0]
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def new_name(path: Path, when: date) -> str:
    """이름에 있던 날짜는 빼고, 맨 앞에 촬영일 하나만 붙인다.
    예: IMG_20260904_150352.mp4 → 20260904_IMG_150352.mp4
        A001_09222312_C006.MP4 (날짜 없음, 수정일 사용) → 20261020_A001_09222312_C006.mp4
    """
    rest = path.stem
    found = find_name_date(rest)
    if found:
        start, end = found[1]
        rest = rest[:start] + "_" + rest[end:]
    rest = SEPARATORS.sub("_", rest).strip("_")
    prefix = f"{when:%Y%m%d}"
    name = f"{prefix}_{rest}" if rest else prefix
    return f"{name}{path.suffix.lower()}"


def destination(path: Path, library: Path, video_exts: list[str], photo_exts: list[str]) -> Path:
    """파일이 LIBRARY 안에서 가야 할 자리."""
    file_kind = kind(path, video_exts, photo_exts)
    if file_kind == UNSORTED:
        return library / UNSORTED / path.name
    when = recording_date(path)
    return library / file_kind / f"{when:%Y-%m-%d}" / new_name(path, when)


def unique_path(path: Path, taken: set[Path]) -> Path:
    """같은 이름이 있으면 덮어쓰지 않고 _2, _3 … 을 붙인다."""
    candidate, counter = path, 2
    while candidate.exists() or candidate in taken:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        counter += 1
    taken.add(candidate)
    return candidate


def load_log(index_dir: Path) -> list[dict]:
    path = index_dir / LOG_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_log(index_dir: Path, entries: list[dict]) -> None:
    path = index_dir / LOG_NAME
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def plan_ingest(files: list[Path], library: Path, index_dir: Path,
                video_exts: list[str], photo_exts: list[str]) -> list[Plan]:
    seen = {(entry["original_name"], entry["size"]) for entry in load_log(index_dir)}
    taken: set[Path] = set()
    plans = []
    for src in sorted(files, key=lambda p: p.name):
        key = (src.name, src.stat().st_size)
        if key in seen:
            plans.append(Plan(src, None, "원본 이름과 크기가 같은 파일이 이미 있음"))
            continue
        seen.add(key)
        dst = unique_path(destination(src, library, video_exts, photo_exts), taken)
        plans.append(Plan(src, dst))
    return plans


def copy_verified(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.parent / f".{dst.name}.partial"
    try:
        shutil.copy2(src, temp)
        if temp.stat().st_size != src.stat().st_size:
            raise OSError(f"복사 후 크기가 다릅니다: {src.name}")
        os.replace(temp, dst)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def run_plan(plans: list[Plan], duplicates: Path, index_dir: Path, library: Path) -> None:
    log = load_log(index_dir)
    for plan in plans:
        try:
            if plan.dst is None:
                target = unique_path(duplicates / plan.src.name, set())
                shutil.move(str(plan.src), target)
                print(f"  중복 이동: {plan.src.name} → DUPLICATES/{target.name}")
                continue
            size = plan.src.stat().st_size
            copy_verified(plan.src, plan.dst)
            plan.src.unlink()
            log.append({
                "original_name": plan.src.name,
                "size": size,
                "dest": str(plan.dst),
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
            })
            save_log(index_dir, log)
            print(f"  정리 완료: {plan.src.name} → {plan.dst.relative_to(library)}")
        except OSError as error:
            print(f"  실패(원본 유지): {plan.src.name} / {error}")
