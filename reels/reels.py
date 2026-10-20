"""릴스 자동화 명령 모음. 사용법: python3 reels/reels.py <명령>

  inbox                       INBOX에 있는 영상과 옮길 계획을 보여준다 (옮기지 않음)
  ingest                      계획만 보여준다 (옮기지 않음)
  ingest --yes                INBOX 영상을 FOOTAGE로 옮기고 중복을 걸러낸다
  script import <파일>         대본(.md/.txt)을 대본 JSON으로 바꾸고 검사한다
  script check <JSON 파일>     대본 JSON을 다시 검사한다
  check                       Gemini 모델이 동작하는지 확인한다
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import ingest  # noqa: E402
import script  # noqa: E402


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

    sub.add_parser("check", help="Gemini 모델 확인").set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
