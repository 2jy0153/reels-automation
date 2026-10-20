"""릴스 자동화 명령 모음. 사용법: python3 reels/reels.py <명령>

  inbox                       INBOX에 있는 영상과 옮길 계획을 보여준다 (옮기지 않음)
  ingest                      계획만 보여준다 (옮기지 않음)
  ingest --yes                INBOX 영상을 FOOTAGE로 옮기고 중복을 걸러낸다
  script import <파일>         대본(.md/.txt)을 대본 JSON으로 바꾸고 검사한다
  script check <JSON 파일>     대본 JSON을 다시 검사한다
  proxy                       FOOTAGE 영상의 720p 분석용 사본을 PROXY에 만든다 (있으면 건너뜀)
  log [--limit N]             사본(없으면 원본)을 Gemini로 분석해 태그를 저장한다 (태깅 안 된 것만)
  check                       Gemini 모델이 동작하는지 확인한다
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import clip_index  # noqa: E402
import common  # noqa: E402
import ingest  # noqa: E402
import proxy  # noqa: E402
import script  # noqa: E402
import tagger  # noqa: E402


def pending_clips(videos: list[Path], clips: dict, limit: int | None) -> list[Path]:
    """아직 태깅이 성공하지 않은 영상만 고른다. 실패한 것은 다시 시도한다."""
    pending = [path for path in videos if clips.get(path.stem, {}).get("status") != "tagged"]
    return pending[:limit] if limit else pending


def print_script_report(errors: list[str], warnings: list[str]) -> None:
    for message in errors:
        print(f"  [오류] {message}")
    for message in warnings:
        print(f"  [주의] {message}")
    if not errors and not warnings:
        print("  검사 통과: 문제가 없습니다.")


def cmd_inbox(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    files = [p for p in sorted(layout["inbox"].iterdir()) if ingest.is_video(p, config["video_exts"])]
    if not files:
        print("INBOX가 비어 있습니다. 영상을 넣은 뒤 다시 확인해 주세요.")
        return
    plans = ingest.plan_ingest(files, layout["footage"], layout["index"])
    print(f"INBOX에 영상 {len(files)}개가 있습니다.")
    for plan in plans:
        size_mb = plan.src.stat().st_size / 1_000_000
        if plan.dst is None:
            print(f"  - {plan.src.name} ({size_mb:.1f} MB) → 중복: DUPLICATES로 이동 ({plan.note})")
        else:
            print(f"  - {plan.src.name} ({size_mb:.1f} MB) → FOOTAGE/{plan.dst.parent.name}/{plan.dst.name}")
    print("정리를 시작하려면 'ingest --yes'를 실행하세요.")


def cmd_ingest(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    files = [p for p in sorted(layout["inbox"].iterdir()) if ingest.is_video(p, config["video_exts"])]
    if not files:
        print("INBOX가 비어 있습니다.")
        return
    plans = ingest.plan_ingest(files, layout["footage"], layout["index"])
    if not args.yes:
        print(f"아직 아무것도 옮기지 않았습니다. 대상 {len(plans)}개. 시작하려면 'ingest --yes'를 실행하세요.")
        return
    print(f"정리를 시작합니다. 대상 {len(plans)}개")
    ingest.run_plan(plans, layout["duplicates"], layout["index"])
    print("정리가 끝났습니다.")


def cmd_script_import(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    source = Path(args.file).expanduser()
    reel_id = args.id or source.stem
    data = script.parse_script(source.read_text(encoding="utf-8"), reel_id)
    data["source_file"] = source.name

    folder = common.make_reel_folder(layout["reels"], reel_id)
    (folder / "script" / source.name).write_bytes(source.read_bytes())  # 원본 대본 보관
    json_path = folder / "script" / f"{reel_id}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"대본 JSON 생성: {json_path}")
    print(f"  줄 {len(data['lines'])}개, 총 {data['length_seconds']}초, 해시태그 {len(data['hashtags'])}개")
    errors, warnings = script.check_script(data)
    print_script_report(errors, warnings)


def cmd_script_check(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
    errors, warnings = script.check_script(data)
    print_script_report(errors, warnings)


def cmd_proxy(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    videos = sorted(p for p in layout["footage"].rglob("*") if ingest.is_video(p, config["video_exts"]))
    todo = [(src, proxy.proxy_path(src, layout["footage"], layout["proxy"])) for src in videos]
    todo = [(src, dst) for src, dst in todo if not dst.exists()]
    if not todo:
        print("만들 사본이 없습니다.")
        return
    print(f"사본 생성 대상 {len(todo)}개 ({config['proxy_height']}p)")
    for src, dst in todo:
        try:
            proxy.make_proxy(src, dst, config["proxy_height"])
            print(f"  사본 완료: {dst.parent.name}/{dst.name}")
        except Exception as error:
            print(f"  사본 실패(원본 유지): {src.name} / {error}")


def cmd_log(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    videos = sorted(p for p in layout["footage"].rglob("*") if ingest.is_video(p, config["video_exts"]))
    clips = clip_index.load_clips(layout["index"])
    pending = pending_clips(videos, clips, args.limit)
    if not pending:
        print("태깅할 클립이 없습니다.")
        return
    print(f"태깅 대상 {len(pending)}개")
    for footage_file in pending:
        # 원본 대신 사본을 올려 업로드 시간과 비용을 줄인다. 사본이 없으면 원본을 쓴다.
        path = proxy.proxy_path(footage_file, layout["footage"], layout["proxy"])
        if not path.exists():
            path = footage_file
        try:
            tags = tagger.analyze_video(path, model=config["gemini_model"])
            record = {"file": str(footage_file), "status": "tagged", **tags}
            print(f"  태깅 완료: {footage_file.name} / {tags['bag_type']} / {tags['person']}")
        except Exception as error:  # 실패해도 기록을 남겨 다음에 다시 시도할 수 있게 한다.
            record = {
                "file": str(footage_file),
                "status": "tag_failed",
                "error": str(error)[:300],
                "bag_type": tagger.UNKNOWN,
                "person": tagger.UNKNOWN,
                "needs_review": True,
            }
            print(f"  태깅 실패: {footage_file.name} / {error}")
        clip_index.upsert_clip(layout["index"], footage_file.stem, record)


def cmd_check(args: argparse.Namespace) -> None:
    import tagger

    config = common.load_config()
    reply = tagger.check_model(config["gemini_model"])
    print(f"모델 {config['gemini_model']} 응답: {reply}")


def main() -> None:
    parser = argparse.ArgumentParser(description="릴스 자동화")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inbox", help="INBOX 확인").set_defaults(func=cmd_inbox)

    ingest_p = sub.add_parser("ingest", help="INBOX 정리 시작")
    ingest_p.add_argument("--yes", action="store_true", help="확인 후 실제로 옮김")
    ingest_p.set_defaults(func=cmd_ingest)

    script_p = sub.add_parser("script", help="대본 처리")
    script_sub = script_p.add_subparsers(dest="script_command", required=True)
    import_p = script_sub.add_parser("import", help="대본 파일을 JSON으로 변환")
    import_p.add_argument("file")
    import_p.add_argument("--id", help="릴스 ID (예: 2026-10-19_backpack_02). 없으면 파일 이름")
    import_p.set_defaults(func=cmd_script_import)
    check_p = script_sub.add_parser("check", help="대본 JSON 검사")
    check_p.add_argument("file")
    check_p.set_defaults(func=cmd_script_check)

    sub.add_parser("proxy", help="분석용 720p 사본 만들기").set_defaults(func=cmd_proxy)

    log_p = sub.add_parser("log", help="영상 태깅 (Gemini)")
    log_p.add_argument("--limit", type=int, help="이번에 처리할 최대 개수 (처음 시험할 때 권장: 2)")
    log_p.set_defaults(func=cmd_log)

    sub.add_parser("check", help="Gemini 모델 확인").set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
