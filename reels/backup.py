"""완성 영상과 썸네일을 구글 드라이브 동기화 폴더로 백업한다.

대상: REELS/<릴스 ID>/export/ 안의 영상과 이미지 (영상과 썸네일은 같은 폴더에 함께 둔다)
복사: 대상 폴더에 같은 파일이 있고 크기가 같으면 건너뛴다. 원본은 건드리지 않는다.
기록: CLIP_INDEX/backup_log.json
"""

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

FINAL_EXTS = {".mp4", ".mov", ".png", ".jpg", ".jpeg"}
LOG_NAME = "backup_log.json"


def finals(reels_dir: Path) -> list[Path]:
    return sorted(
        p for p in reels_dir.glob("*/export/*")
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in FINAL_EXTS
    )


def target_for(drive_dir: Path, source: Path) -> Path:
    """백업 폴더 안에 하위 폴더 없이 파일만 둔다. 같은 이름이 다른 크기로 있으면 릴스 ID를 앞에 붙인다."""
    candidate = drive_dir / source.name
    if candidate.exists() and candidate.stat().st_size != source.stat().st_size:
        candidate = drive_dir / f"{source.parent.parent.name}_{source.name}"
    return candidate


def needs_copy(source: Path, target: Path) -> bool:
    return not target.exists() or target.stat().st_size != source.stat().st_size


def backup_once(reels_dir: Path, drive_dir: Path, index_dir: Path) -> list[Path]:
    log_path = index_dir / LOG_NAME
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    copied = []
    for source in finals(reels_dir):
        target = target_for(drive_dir, source)
        if not needs_copy(source, target):
            continue
        drive_dir.mkdir(parents=True, exist_ok=True)
        temp = target.parent / f".{target.name}.partial"
        try:
            shutil.copy2(source, temp)
            if temp.stat().st_size != source.stat().st_size:
                raise OSError(f"복사 후 크기가 다릅니다: {source.name}")
            os.replace(temp, target)
        except OSError as error:
            temp.unlink(missing_ok=True)
            print(f"  백업 실패: {source.name} / {error}")
            continue
        copied.append(target)
        log.append({"source": str(source), "target": str(target),
                    "backed_up_at": datetime.now().isoformat(timespec="seconds")})
    index_dir.mkdir(parents=True, exist_ok=True)
    temp_log = log_path.with_suffix(".json.tmp")
    temp_log.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_log, log_path)
    return copied


def watch(reels_dir: Path, drive_dir: Path, index_dir: Path, interval: int) -> None:
    """지정한 간격으로 새 완성본이 있는지 확인하고 백업한다. 끊기지 않도록 계속 돈다."""
    while True:
        try:
            if not drive_dir.is_dir():
                print("백업 폴더가 보이지 않습니다. 구글 드라이브 앱이 켜져 있는지 확인합니다.")
            else:
                for path in backup_once(reels_dir, drive_dir, index_dir):
                    print(f"백업 완료: {path}")
        except Exception as error:  # 한 번 실패해도 감시는 계속한다.
            print(f"백업 중 오류: {error}")
        time.sleep(interval)
