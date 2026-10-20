"""INBOX의 파일을 LIBRARY 안의 알맞은 자리로 옮긴다.

- 영상 → LIBRARY/VIDEO/YYYYMMDD/YYYYMMDD_원래이름.확장자
- 사진 → LIBRARY/PHOTO/YYYYMMDD/YYYYMMDD_원래이름.확장자
- 날짜를 못 찾은 영상·사진 → LIBRARY/_NO_DATE/원래이름 (직접 확인 후 옮김)
- 영상도 사진도 아닌 파일 → LIBRARY/_UNSORTED/원래이름
- 날짜 출처: 파일명의 YYYYMMDD → 메타데이터(EXIF 등, exiftool). 파일 수정일은 쓰지 않는다.
- 중복: 원본 이름과 크기가 같으면 먼저 들어온 한 개만 남기고 DUPLICATES로 뺀다
- 원본은 복사본의 크기가 같다고 확인된 뒤에만 INBOX에서 지운다
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
SEPARATORS = re.compile(r"[_\-\s]+")
LOG_NAME = "ingest_log.json"
VIDEO = "VIDEO"
PHOTO = "PHOTO"
UNSORTED = "_UNSORTED"
NO_DATE = "_NO_DATE"
# 메타데이터에서 촬영일로 볼 태그 순서. 앞에 있는 것을 우선한다.
DATE_TAGS = ["DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"]

MetadataReader = Callable[[Path], "date | None"]


@dataclass(frozen=True)
class Plan:
    src: Path
    dst: Path
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


def metadata_date(path: Path) -> date | None:
    """exiftool로 메타데이터의 촬영일을 읽는다. 없거나 0000이면 None."""
    if shutil.which("exiftool") is None:
        raise RuntimeError("exiftool이 설치되어 있지 않습니다. 날짜를 메타데이터에서 읽을 수 없어 중단합니다.")
    result = subprocess.run(
        ["exiftool", "-j", "-api", "QuickTimeUTC=1", *[f"-{tag}" for tag in DATE_TAGS], str(path)],
        capture_output=True, text=True, check=True,
    )
    record = json.loads(result.stdout)[0]
    for tag in DATE_TAGS:
        value = str(record.get(tag, ""))
        if len(value) >= 10 and not value.startswith("0000"):
            try:
                return date.fromisoformat(value[:10].replace(":", "-"))
            except ValueError:
                continue
    return None


def recording_date(path: Path, metadata_reader: MetadataReader = metadata_date) -> date | None:
    found = find_name_date(path.stem)
    return found[0] if found else metadata_reader(path)


def new_name(path: Path, when: date) -> str:
    """이름에 있던 날짜는 빼고, 맨 앞에 촬영일 하나만 붙인다.
    예: IMG_20260904_150352.mp4 → 20260904_IMG_150352.mp4
        A001_09222312_C006.MP4 (날짜 없음, 메타데이터 사용) → 20261020_A001_09222312_C006.mp4
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


def destination(path: Path, library: Path, video_exts: list[str], photo_exts: list[str],
                metadata_reader: MetadataReader = metadata_date) -> Path:
    """파일이 LIBRARY 안에서 가야 할 자리."""
    file_kind = kind(path, video_exts, photo_exts)
    if file_kind == UNSORTED:
        return library / UNSORTED / path.name
    when = recording_date(path, metadata_reader)
    if when is None:
        return library / NO_DATE / path.name
    return library / file_kind / f"{when:%Y%m%d}" / new_name(path, when)


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


def plan_ingest(files: list[Path], library: Path, index_dir: Path, video_exts: list[str],
                photo_exts: list[str], duplicates: Path, metadata_reader: MetadataReader = metadata_date) -> list[Plan]:
    seen = {(entry["original_name"], entry["size"]) for entry in load_log(index_dir)}
    taken: set[Path] = set()
    plans = []
    for src in sorted(files, key=lambda p: p.name):
        key = (src.name, src.stat().st_size)
        if key in seen:
            plans.append(Plan(src, unique_path(duplicates / src.name, taken), "이미 정리된 파일과 이름·크기가 같음"))
            continue
        seen.add(key)
        dst = unique_path(destination(src, library, video_exts, photo_exts, metadata_reader), taken)
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


def run_plan(plans: list[Plan], index_dir: Path, library: Path) -> None:
    log = load_log(index_dir)
    for plan in plans:
        try:
            if plan.note:  # 중복: 옮기기만 하고 기록은 남기지 않는다 (원본은 이미 기록되어 있음)
                shutil.move(str(plan.src), plan.dst)
                print(f"  중복 이동: {plan.src.name} → DUPLICATES/{plan.dst.name}")
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
