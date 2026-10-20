"""설정 읽기, 폴더 구조, 공통 도구."""

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 릴스 1편 = REELS/<id>/ 폴더 하나. 안의 하위 폴더는 작업 단계별로 나뉜다.
REEL_SUBFOLDERS = ["script", "voice", "subtitles", "graded", "project", "export", "thumbnail"]


def load_env_file() -> None:
    """reels/.env의 KEY=VALUE 줄을 환경 변수로 읽는다. 이미 있는 값은 덮어쓰지 않는다."""
    env_path = HERE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> dict:
    load_env_file()
    return json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def resolve_root(config: dict) -> Path:
    # REELS_ROOT는 테스트용 임시 폴더를 가리킬 때만 쓴다.
    root = Path(os.environ.get("REELS_ROOT", config["source_root"]))
    # SSD가 안 꽂혀 있으면 내장 디스크에 폴더를 만들지 않도록 여기서 멈춘다.
    if not root.is_dir():
        raise SystemExit(f"SSD가 연결되지 않았거나 폴더가 없습니다: {root}")
    return root


def make_layout(root: Path) -> dict[str, Path]:
    layout = {
        "inbox": root / "INBOX",              # 새 영상을 넣는 곳
        "library": root / "LIBRARY",          # 원본 보관 (날짜별, 수정·삭제 금지)
        "proxy": root / "PROXY",              # 분석용 저용량 사본 (날짜별)
        "duplicates": root / "DUPLICATES",    # 중복으로 빠진 파일 (확인 후 직접 삭제)
        "index": root / "CLIP_INDEX",         # 클립 정보, 수집 기록, 로그
        "reels": root / "REELS",              # 릴스 1편 작업 폴더
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


def make_reel_folder(reels_dir: Path, reel_id: str) -> Path:
    folder = reels_dir / reel_id
    for name in REEL_SUBFOLDERS:
        (folder / name).mkdir(parents=True, exist_ok=True)
    return folder
