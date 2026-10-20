"""릴스 자동화 명령 모음. 사용법: python3 reels/reels.py <명령>

  inbox                       INBOX 파일과 옮길 계획을 보여준다 (옮기지 않음)
  ingest --yes                INBOX 파일을 LIBRARY의 알맞은 자리로 옮긴다 (영상/사진/기타)
  organize                    LIBRARY 기존 파일을 옮길 계획만 보여준다 (옮기지 않음)
  organize --yes              위 계획대로 실제로 옮긴다 (중복·빈 폴더는 건드리지 않음)
  script import <파일>         대본(.md/.txt)을 대본 JSON으로 바꾸고 검사한다
  script check <JSON 파일>     대본 JSON을 다시 검사한다
  proxy                       LIBRARY/VIDEO 영상의 720p 분석용 사본을 PROXY에 만든다 (있으면 건너뜀)
  log [--limit N]             영상(사본 우선)을 Gemini로 분석해 태그를 저장한다 (태깅 안 된 것만)
  check                       Gemini 모델이 동작하는지 확인한다
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import clip_index  # noqa: E402
import media_info  # noqa: E402
import common  # noqa: E402
import ingest  # noqa: E402
import organize  # noqa: E402
import proxy  # noqa: E402
import script  # noqa: E402
import subtitles  # noqa: E402
import tagger  # noqa: E402
import voice  # noqa: E402


def pending_clips(videos: list[Path], clips: dict, limit: int | None) -> list[Path]:
    """아직 태깅이 성공하지 않은 영상만 고른다. 실패한 것은 다시 시도한다."""
    pending = [path for path in videos if clips.get(path.stem, {}).get("status") != "tagged"]
    return pending[:limit] if limit else pending


def library_videos(library: Path, video_exts: list[str]) -> list[Path]:
    return sorted(
        p for p in library.rglob("*")
        if ingest.is_file_to_handle(p) and ingest.kind(p, video_exts, []) == ingest.VIDEO
    )


def inbox_files(inbox: Path) -> list[Path]:
    return sorted(p for p in inbox.iterdir() if ingest.is_file_to_handle(p))


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
    files = inbox_files(layout["inbox"])
    if not files:
        print("INBOX가 비어 있습니다. 파일을 넣은 뒤 다시 확인해 주세요.")
        return
    plans = ingest.plan_ingest(files, layout["library"], layout["index"], config["video_exts"],
                               config["photo_exts"], layout["duplicates"])
    print(f"INBOX에 파일 {len(files)}개가 있습니다.")
    for plan in plans:
        size_mb = plan.src.stat().st_size / 1_000_000
        if plan.note:
            print(f"  - {plan.src.name} ({size_mb:.1f} MB) → 중복: DUPLICATES로 이동 ({plan.note})")
        else:
            print(f"  - {plan.src.name} ({size_mb:.1f} MB) → {plan.dst.relative_to(layout['library'].parent)}")
    print("정리를 시작하려면 'ingest --yes'를 실행하세요.")


def cmd_ingest(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    files = inbox_files(layout["inbox"])
    if not files:
        print("INBOX가 비어 있습니다.")
        return
    plans = ingest.plan_ingest(files, layout["library"], layout["index"], config["video_exts"],
                               config["photo_exts"], layout["duplicates"])
    if not args.yes:
        print(f"아직 아무것도 옮기지 않았습니다. 대상 {len(plans)}개. 시작하려면 'ingest --yes'를 실행하세요.")
        return
    print(f"정리를 시작합니다. 대상 {len(plans)}개")
    ingest.run_plan(plans, layout["index"], layout["library"])
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


def cmd_organize(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    moves = organize.plan_organize(layout["library"], layout["duplicates"], config["video_exts"], config["photo_exts"])
    if not moves:
        print("LIBRARY에 파일이 없습니다.")
        return
    kept = [m for m in moves if m.dst == m.src]
    to_move = [m for m in moves if m.dst != m.src]
    print(f"LIBRARY 파일 {len(moves)}개: 옮김 {len(to_move)}개, 그대로 둠 {len(kept)}개")
    for move in to_move:
        target = move.dst.relative_to(layout["library"].parent)
        print(f"  - {move.src.relative_to(layout['library'])} → {target}" + (f" ({move.note})" if move.note else ""))
    for move in kept:
        print(f"  - 그대로 둠: {move.src.relative_to(layout['library'])}")
    if not args.yes:
        print("아직 아무것도 옮기지 않았습니다. 진행하려면 'organize --yes'를 실행하세요.")
        return
    organize.apply_organize(moves, layout["index"])


def cmd_fix_folders(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    bases = [layout["library"] / "VIDEO", layout["library"] / "PHOTO", layout["proxy"] / "VIDEO"]
    renames = organize.plan_folder_renames(bases)
    if not renames:
        print("바꿀 폴더가 없습니다.")
        return
    print(f"바꿀 폴더 {len(renames)}개:")
    for old, new in renames:
        print(f"  - {old.relative_to(layout['library'].parent)} → {new.name}")
    if not args.yes:
        print("아직 아무것도 바꾸지 않았습니다. 진행하려면 'fix-folders --yes'를 실행하세요.")
        return
    organize.apply_folder_renames(renames, layout["index"])


def cmd_proxy(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    videos = library_videos(layout["library"], config["video_exts"])
    todo = [(src, proxy.proxy_path(src, layout["library"], layout["proxy"])) for src in videos]
    todo = [(src, dst) for src, dst in todo if not dst.exists()]
    if not todo:
        print("만들 사본이 없습니다.")
        return
    print(f"사본 생성 대상 {len(todo)}개 ({config['proxy_height']}p)")
    for src, dst in todo:
        try:
            proxy.make_proxy(src, dst, config["proxy_height"])
            print(f"  사본 완료: {dst.relative_to(layout['proxy'])}")
        except Exception as error:
            print(f"  사본 실패(원본 유지): {src.name} / {error}")


def cmd_log(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    videos = library_videos(layout["library"], config["video_exts"])
    clips = clip_index.load_clips(layout["index"])
    pending = pending_clips(videos, clips, args.limit)
    if not pending:
        print("태깅할 클립이 없습니다.")
        return
    print(f"태깅 대상 {len(pending)}개")
    for library_file in pending:
        # 원본 대신 사본을 올려 업로드 시간과 비용을 줄인다. 사본이 없으면 원본을 쓴다.
        path = proxy.proxy_path(library_file, layout["library"], layout["proxy"])
        if not path.exists():
            path = library_file
        try:
            tags = tagger.analyze_video(path, model=config["gemini_model"])
            record = {"file": str(library_file), "status": "tagged", **tags,
                      "orientation": media_info.orientation_of(library_file)}
            print(f"  태깅 완료: {library_file.name} / {tags['bag_type']} / {tags['person']}")
        except Exception as error:  # 실패해도 기록을 남겨 다음에 다시 시도할 수 있게 한다.
            if tagger.is_quota_error(error):
                print(f"  한도 도달로 멈춤: {error}")
                print("  남은 영상은 다음에 'log'를 실행하면 이어서 처리합니다.")
                return
            record = {
                "file": str(library_file),
                "status": "tag_failed",
                "error": str(error)[:300],
                "bag_type": tagger.UNKNOWN,
                "person": tagger.UNKNOWN,
                "needs_review": True,
            }
            print(f"  태깅 실패: {library_file.name} / {error}")
        clip_index.upsert_clip(layout["index"], library_file.stem, record)


def cmd_voice(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    folder = layout["reels"] / args.reel_id
    script_path = folder / "script" / f"{args.reel_id}.json"
    if not script_path.exists():
        raise SystemExit(f"대본 JSON이 없습니다. 먼저 'script import'를 실행하세요: {script_path}")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    lines = data["lines"]
    voice_dir = folder / "voice"
    raw_dir = voice_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    missing = [line for line in lines if not (raw_dir / f"{line['no']:02d}.mp3").exists()]

    if not args.yes and args.speed is None:
        chars = sum(len(line["narration"]) for line in lines)
        print(f"나레이션 {len(lines)}줄, 총 {chars}자. 원본 음성 있음 {len(lines) - len(missing)}개, 새로 만들 음성 {len(missing)}개")
        print("원본 음성을 만들려면 'voice <ID> --yes', 배속을 정해 타임라인을 만들려면 'voice <ID> --speed 1.1'을 실행하세요.")
        return

    if missing:
        if not args.yes:
            raise SystemExit(f"원본 음성 {len(missing)}개가 없습니다. 먼저 'voice <ID> --yes'를 실행하세요.")
        if not config["elevenlabs_voice_id"]:
            raise SystemExit("config.json의 elevenlabs_voice_id가 비어 있습니다. 목소리 ID를 넣은 뒤 다시 실행하세요.")
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise SystemExit("reels/.env에 ELEVENLABS_API_KEY가 없습니다.")
        for line in missing:
            print(f"  원본 음성 생성: {line['no']}번")
            raw_path = raw_dir / f"{line['no']:02d}.mp3"
            raw_path.write_bytes(voice.synthesize(line["narration"], config["elevenlabs_voice_id"],
                                                  config["elevenlabs_model"], api_key))

    speed = args.speed if args.speed is not None else 1.0
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg/ffprobe가 설치되어 있지 않습니다.")
    durations = []
    for line in lines:
        name = f"{line['no']:02d}.mp3"
        final_path = voice_dir / name
        if args.speed is not None or not final_path.exists():
            voice.apply_speed(raw_dir / name, final_path, speed)
        durations.append(voice.duration(final_path))

    timeline = voice.build_timeline(lines, durations, config["pause_seconds"], config["pause_after_question_seconds"])
    voice.write_timeline(voice_dir, speed, timeline)
    print(f"배속 {speed}로 음성을 만들었습니다. 실제 길이 기준 타임라인:")
    for item in timeline:
        print(f"  {item['no']}번: {item['start']}초 ~ {item['end']}초 (길이 {item['duration']}초), 다음 줄까지 쉼 {item['pause_after']}초")
    print(f"총 길이 약 {timeline[-1]['end']}초. 저장: {voice_dir / voice.TIMELINE}")
    print("음성을 들어 보고 다른 배속이 필요하면 'voice <ID> --speed 값'을 다시 실행하세요.")


def cmd_split_voice(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    folder = layout["reels"] / args.reel_id
    script_path = folder / "script" / f"{args.reel_id}.json"
    if not script_path.exists():
        raise SystemExit(f"대본 JSON이 없습니다: {script_path}")
    lines = json.loads(script_path.read_text(encoding="utf-8"))["lines"]
    voice_dir = folder / "voice"
    raw_dir = voice_dir / "raw"

    if args.file:
        source = Path(args.file).expanduser()
    else:
        # 확장자 대소문자(.mp3, .MP3)와 상관없이 voice 폴더의 음성 파일을 찾는다.
        candidates = sorted(p for p in voice_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")
        if len(candidates) != 1:
            raise SystemExit(f"voice 폴더에 mp3가 {len(candidates)}개 있습니다. 파일을 지정하세요: split-voice <ID> <파일>")
        source = candidates[0]
    if not source.exists():
        raise SystemExit(f"음성 파일을 찾을 수 없습니다: {source}")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg가 설치되어 있지 않습니다.")

    total = voice.duration(source)
    silences = voice.detect_silences(source)
    char_counts = [len(re.sub(r"\s", "", line["narration"])) for line in lines]
    try:
        cuts = voice.choose_cuts_by_text(silences, total, char_counts)
    except ValueError as error:
        raise SystemExit(str(error))
    segments = voice.segments_from_cuts(total, cuts)
    print(f"원본 {source.name}: 총 {total:.2f}초, 무음 구간 {len(silences)}개, 문단 {len(lines)}개")
    rates = [chars / (end - start) for chars, (start, end) in zip(char_counts, segments) if end > start]
    average = sum(rates) / len(rates) if rates else 0
    for line, chars, (start, end) in zip(lines, char_counts, segments):
        seconds = end - start
        rate = chars / seconds if seconds > 0 else 0
        flag = "  <- 확인 필요" if average and abs(rate - average) / average > 0.4 else ""
        print(f"  {line['no']:02d}번 {start:7.2f}~{end:7.2f}초 ({seconds:.2f}초, {chars}자, 초당 {rate:.1f}자){flag}: {line['narration'][:25]}")
    if not args.yes:
        print("아직 아무것도 저장하지 않았습니다. 확인 후 'split-voice <ID> --yes'를 실행하세요.")
        return
    if any((raw_dir / f"{line['no']:02d}.mp3").exists() for line in lines) and not args.force:
        raise SystemExit("raw 폴더에 이미 음성이 있습니다. 덮어쓰려면 --force를 붙이세요.")
    for line, (start, end) in zip(lines, segments):
        voice.cut_audio(source, raw_dir / f"{line['no']:02d}.mp3", start, end)
    print(f"저장 완료: {raw_dir} (문단 {len(lines)}개). 다음은 'voice <ID> --speed 값'입니다.")


def cmd_srt(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    folder = layout["reels"] / args.reel_id
    voice_dir = folder / "voice"
    if not (voice_dir / "timeline.json").exists():
        raise SystemExit("timeline.json이 없습니다. 먼저 'voice <ID> --speed 값'을 실행하세요.")
    timeline = subtitles.load_timeline(voice_dir)
    out = folder / "subtitles" / f"{args.reel_id}.srt"
    out.parent.mkdir(parents=True, exist_ok=True)
    style = config["subtitle"]
    out.write_text(subtitles.build_srt(timeline, style), encoding="utf-8")
    print(f"자막 한 줄 최대 {subtitles.chars_per_line(style)}자, 블록 최대 {subtitles.max_chars_per_cue(style)}자 (임시 디자인 값)")
    print(f"자막 저장: {out} ({len(timeline)}개)")


def cmd_orient(args: argparse.Namespace) -> None:
    config = common.load_config()
    layout = common.make_layout(common.resolve_root(config))
    videos = library_videos(layout["library"], config["video_exts"])
    clips = clip_index.load_clips(layout["index"])
    todo = [p for p in videos if args.force or "orientation" not in clips.get(p.stem, {})]
    if not todo:
        print("방향을 확인할 영상이 없습니다.")
        return
    print(f"방향 확인 대상 {len(todo)}개 (Gemini 사용 없음)")
    for path in todo:
        try:
            labels = media_info.orientation_of(path)
        except Exception as error:
            print(f"  확인 실패: {path.name} / {error}")
            continue
        clip_index.upsert_clip(layout["index"], path.stem, {"file": str(path), "orientation": labels})
        print(f"  {path.name}: {' → '.join(labels) or '알 수 없음'}")


def cmd_check(args: argparse.Namespace) -> None:
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
    import_p.add_argument("--id", help="릴스 ID (예: 20261019_backpack_02). 없으면 파일 이름")
    import_p.set_defaults(func=cmd_script_import)
    check_p = script_sub.add_parser("check", help="대본 JSON 검사")
    check_p.add_argument("file")
    check_p.set_defaults(func=cmd_script_check)

    organize_p = sub.add_parser("organize", help="LIBRARY 기존 파일을 종류·날짜별 구조로 정리")
    organize_p.add_argument("--yes", action="store_true", help="확인 후 실제로 옮김")
    organize_p.set_defaults(func=cmd_organize)

    sub.add_parser("proxy", help="분석용 720p 사본 만들기").set_defaults(func=cmd_proxy)

    fix_p = sub.add_parser("fix-folders", help="VIDEO·PHOTO·PROXY의 YYYY-MM-DD 폴더를 YYYYMMDD로 바꾸기 (한 번만)")
    fix_p.add_argument("--yes", action="store_true", help="확인 후 실제로 바꿈")
    fix_p.set_defaults(func=cmd_fix_folders)

    log_p = sub.add_parser("log", help="영상 태깅 (Gemini)")
    log_p.add_argument("--limit", type=int, help="이번에 처리할 최대 개수 (처음 시험할 때 권장: 2)")
    log_p.set_defaults(func=cmd_log)

    voice_p = sub.add_parser("voice", help="대본으로 나레이션 생성 (ElevenLabs)")
    voice_p.add_argument("reel_id", help="릴스 ID (예: 20261019_backpack_02)")
    voice_p.add_argument("--yes", action="store_true", help="원본 음성을 ElevenLabs로 만듦 (없는 것만)")
    voice_p.add_argument("--speed", type=float, help="배속을 정해 최종 음성과 타임라인을 다시 만듦 (예: 1.1)")
    voice_p.set_defaults(func=cmd_voice)

    split_p = sub.add_parser("split-voice", help="전체 음성 mp3를 문단별로 자르기")
    split_p.add_argument("reel_id")
    split_p.add_argument("file", nargs="?", help="음성 파일 (생략하면 voice 폴더의 mp3 하나)")
    split_p.add_argument("--yes", action="store_true", help="확인 후 실제로 저장")
    split_p.add_argument("--force", action="store_true", help="raw 폴더의 기존 음성을 덮어씀")
    split_p.set_defaults(func=cmd_split_voice)

    srt_p = sub.add_parser("srt", help="타임라인으로 자막(SRT) 만들기")
    srt_p.add_argument("reel_id")
    srt_p.set_defaults(func=cmd_srt)

    orient_p = sub.add_parser("orient", help="영상 방향(세로/가로) 태그 달기 (Gemini 미사용)")
    orient_p.add_argument("--force", action="store_true", help="이미 확인한 영상도 다시 확인")
    orient_p.set_defaults(func=cmd_orient)

    sub.add_parser("check", help="Gemini 모델 확인").set_defaults(func=cmd_check)

    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as error:
        raise SystemExit(f"중단: {error}")


if __name__ == "__main__":
    main()
