import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clip_index  # noqa: E402
import ingest  # noqa: E402
import script  # noqa: E402
import tagger  # noqa: E402

VEXTS = [".mp4", ".mov"]
PEXTS = [".jpg", ".heic"]


def no_metadata(path):
    return None  # 메타데이터에 날짜가 없는 경우를 흉내 낸다 (exiftool을 부르지 않음)
FIXTURE = Path(__file__).parent / "fixtures" / "script_v3.md"


class MetadataDateTests(unittest.TestCase):
    def read(self, exif_output):
        from unittest import mock

        import ingest as ingest_mod

        completed = mock.Mock(stdout=exif_output)
        with mock.patch.object(ingest_mod.shutil, "which", return_value="/usr/bin/exiftool"), \
                mock.patch.object(ingest_mod.subprocess, "run", return_value=completed):
            return ingest_mod.metadata_date(Path("x.mp4"))

    def test_reads_capture_date_and_skips_zero_dates(self):
        out = '[{"CreateDate": "0000:00:00 00:00:00", "DateTimeOriginal": "2026:07:11 18:29:15"}]'
        self.assertEqual(self.read(out), date(2026, 7, 11))

    def test_returns_none_when_no_date_tag(self):
        self.assertIsNone(self.read('[{"SourceFile": "x.mp4"}]'))

    def test_missing_exiftool_stops_with_clear_error(self):
        from unittest import mock

        import ingest as ingest_mod

        with mock.patch.object(ingest_mod.shutil, "which", return_value=None):
            with self.assertRaises(RuntimeError):
                ingest_mod.metadata_date(Path("x.mp4"))


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox = base / "INBOX"
        self.library = base / "LIBRARY"
        self.duplicates = base / "DUPLICATES"
        self.index = base / "CLIP_INDEX"
        for folder in (self.inbox, self.library, self.duplicates, self.index):
            folder.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, content=b"video", mtime=None):
        path = self.inbox / name
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def make_in(self, folder_name, name, content):
        folder = self.inbox / folder_name
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return path

    def plan(self, files):
        return ingest.plan_ingest(files, self.library, self.index, VEXTS, PEXTS, self.duplicates, no_metadata)

    def test_skips_macos_metadata(self):
        self.assertFalse(ingest.is_file_to_handle(self.make("._20260906_094555.mp4")))
        self.assertFalse(ingest.is_file_to_handle(self.make(".DS_Store")))
        self.assertTrue(ingest.is_file_to_handle(self.make("clip.MP4")))

    def test_kind_splits_video_photo_and_other(self):
        self.assertEqual(ingest.kind(Path("a.MP4"), VEXTS, PEXTS), ingest.VIDEO)
        self.assertEqual(ingest.kind(Path("a.HEIC"), VEXTS, PEXTS), ingest.PHOTO)
        self.assertEqual(ingest.kind(Path("memo.pdf"), VEXTS, PEXTS), ingest.UNSORTED)

    def test_name_is_date_then_original_name_when_no_date_in_name(self):
        self.assertEqual(ingest.new_name(Path("A001_09222312_C006.MP4"), date(2026, 9, 22)),
                         "20260922_A001_09222312_C006.mp4")

    def test_date_inside_name_is_moved_to_front_once(self):
        self.assertEqual(ingest.new_name(Path("20260904_150352.mp4"), date(2026, 9, 4)), "20260904_150352.mp4")
        self.assertEqual(ingest.new_name(Path("IMG_20260904_150352.mp4"), date(2026, 9, 4)),
                         "20260904_IMG_150352.mp4")
        self.assertEqual(ingest.new_name(Path("A001_20260922_C006.mp4"), date(2026, 9, 22)),
                         "20260922_A001_C006.mp4")

    def test_filename_date_wins_over_metadata(self):
        path = Path("20260904_150352.mp4")
        self.assertEqual(ingest.recording_date(path, lambda p: date(2020, 1, 1)), date(2026, 9, 4))

    def test_camera_code_is_not_a_date_so_metadata_is_used(self):
        path = Path("A001_09222312_C006.mp4")
        self.assertEqual(ingest.recording_date(path, lambda p: date(2026, 10, 1)), date(2026, 10, 1))

    def test_no_filename_date_and_no_metadata_means_no_date(self):
        self.assertIsNone(ingest.recording_date(Path("A001_09222312_C006.mp4"), no_metadata))

    def test_file_date_is_never_taken_from_modified_time(self):
        path = self.make("A001_09222312_C006.mp4", mtime=1_700_000_000)
        self.assertIsNone(ingest.recording_date(path, no_metadata))

    def test_destination_by_kind(self):
        video = ingest.destination(self.make("20260904_150352.mp4"), self.library, VEXTS, PEXTS)
        photo = ingest.destination(self.make("20260904_IMG_1.heic"), self.library, VEXTS, PEXTS)
        other = ingest.destination(self.make("memo.pdf"), self.library, VEXTS, PEXTS)
        undated = ingest.destination(self.make("clip.mp4"), self.library, VEXTS, PEXTS, no_metadata)
        self.assertEqual(video, self.library / "VIDEO" / "20260904" / "20260904_150352.mp4")
        self.assertEqual(photo, self.library / "PHOTO" / "20260904" / "20260904_IMG_1.heic")
        self.assertEqual(other, self.library / "_UNSORTED" / "memo.pdf")
        self.assertEqual(undated, self.library / "_NO_DATE" / "clip.mp4")

    def test_same_name_and_size_in_one_batch_keeps_first_only(self):
        first = self.make_in("a", "20260904_150352.mp4", b"abc")
        second = self.make_in("b", "20260904_150352.mp4", b"abc")
        plans = self.plan([first, second])
        self.assertFalse(plans[0].note)
        self.assertTrue(plans[1].note)

    def test_same_name_different_size_is_kept_with_suffix(self):
        a = self.make_in("a", "x.mp4", b"abc")
        b = self.make_in("b", "x.mp4", b"abcdef")
        plans = self.plan([a, b])
        self.assertIsNotNone(plans[0].dst)
        self.assertIsNotNone(plans[1].dst)
        self.assertNotEqual(plans[0].dst, plans[1].dst)

    def test_run_moves_verified_copy_and_records_log(self):
        src = self.make("20260904_150352.mp4", b"abc")
        ingest.run_plan(self.plan([src]), self.index, self.library)
        final = self.library / "VIDEO" / "20260904" / "20260904_150352.mp4"
        self.assertEqual(final.read_bytes(), b"abc")
        self.assertFalse(src.exists())
        log = ingest.load_log(self.index)
        self.assertEqual(log[0]["original_name"], "20260904_150352.mp4")
        self.assertEqual(log[0]["size"], 3)

    def test_already_ingested_file_becomes_duplicate_on_next_run(self):
        first = self.make("20260904_150352.mp4", b"abc")
        ingest.run_plan(self.plan([first]), self.index, self.library)

        again = self.make("20260904_150352.mp4", b"abc")
        plans = self.plan([again])
        self.assertTrue(plans[0].note)
        ingest.run_plan(plans, self.index, self.library)
        self.assertTrue((self.duplicates / "20260904_150352.mp4").exists())
        self.assertEqual(len(list(self.library.rglob("*.mp4"))), 1)

    def test_no_overwrite_when_destination_exists(self):
        (self.library / "VIDEO" / "20260904").mkdir(parents=True)
        (self.library / "VIDEO" / "20260904" / "20260904_150352.mp4").write_bytes(b"old")
        src = self.make("20260904_150352.mp4", b"newer-content")
        self.assertEqual(self.plan([src])[0].dst.name, "20260904_150352_2.mp4")


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.data = script.parse_script(FIXTURE.read_text(encoding="utf-8"), "20261019_backpack_01")

    def test_reads_every_table_row_with_times(self):
        self.assertEqual(len(self.data["lines"]), 8)
        first = self.data["lines"][0]
        self.assertEqual((first["target_start"], first["target_end"]), (0, 3))
        self.assertEqual(first["narration"], "20대 땐 백팩은 촌스럽다고 생각했어요.")

    def test_no_caption_marker_becomes_none(self):
        self.assertIsNone(self.data["lines"][6]["caption"])

    def test_reads_title_hashtags_thumbnail_and_caption_body(self):
        self.assertIn("백팩", self.data["title"])
        self.assertIn("#백팩", self.data["hashtags"])
        self.assertEqual(len(self.data["thumbnail_texts"]), 4)
        self.assertIn("디렉터", self.data["caption_body"])
        self.assertEqual(self.data["length_seconds"], 36)

    def test_long_narration_is_not_an_error_or_warning(self):
        # 시간을 넘는 대사는 배속으로 맞추므로 검사에서 막지 않는다.
        errors, warnings = script.check_script(self.data)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            script.parse_script("   \n  ", "x")

    def test_plain_text_with_time_markers(self):
        text = "# 제목\n\n0~3초 첫 문장입니다.\n자막: 큰 글씨\n3~6초 둘째 문장인가요?\n\n본문\n가방 이야기\n\n썸네일\n첫 줄\n둘째 줄\n\n#백팩 #출근"
        data = script.parse_script(text, "20261021_test_01")
        self.assertEqual(len(data["lines"]), 2)
        self.assertEqual((data["lines"][1]["target_start"], data["lines"][1]["target_end"]), (3, 6))
        self.assertEqual(data["lines"][0]["caption"], "큰 글씨")
        self.assertFalse(data["timing_estimated"])
        self.assertEqual(data["caption_body"], "가방 이야기")
        self.assertEqual(data["thumbnail_texts"], ["첫 줄", "둘째 줄"])
        self.assertIn("#백팩", data["hashtags"])
        self.assertEqual(script.check_script(data), ([], []))

    def test_plain_text_without_markers_estimates_timing(self):
        text = "가나다라마바사아자차 카타파하.\n\n두 번째 문단입니다."
        data = script.parse_script(text, "x")
        self.assertEqual(len(data["lines"]), 2)
        self.assertTrue(data["timing_estimated"])
        self.assertEqual(data["lines"][0]["target_end"], 2)  # 10자 / 6자 ≈ 2초
        errors, warnings = script.check_script(data)
        self.assertEqual(errors, [])
        self.assertTrue(any("예상" in w for w in warnings))

    def test_plain_text_labels_for_visual_and_narration(self):
        text = "0~4초\n화면: 옷장 앞\n대사: 백팩 이야기를 시작합니다."
        data = script.parse_script(text, "x")
        self.assertEqual(data["lines"][0]["visual"], "옷장 앞")
        self.assertEqual(data["lines"][0]["narration"], "백팩 이야기를 시작합니다.")

    def test_horizontal_rule_is_not_narration(self):
        data = script.parse_script("첫 문단입니다.\n\n---\n\n둘째 문단입니다.", "x")
        self.assertEqual([line["narration"] for line in data["lines"]], ["첫 문단입니다.", "둘째 문단입니다."])

    def test_text_before_first_marker_is_rejected(self):
        with self.assertRaises(ValueError):
            script.parse_script("앞 내용\n0~3초 뒤 내용", "x")

    def test_end_before_start_is_error(self):
        errors, _ = script.check_script({"lines": [
            {"no": 1, "target_start": 5, "target_end": 3, "narration": "가", "caption": None}]})
        self.assertTrue(errors)


class CutByTextTests(unittest.TestCase):
    def test_cuts_follow_character_share_not_silence_length(self):
        import voice as voice_mod

        # 문단 1은 10자, 문단 2는 30자, 문단 3은 10자 → 경계 목표는 4초와 16초.
        # 가장 긴 무음이 아니라 목표에 가장 가까운 무음을 골라야 한다.
        silences = [(1.0, 1.1), (5.0, 5.8), (8.0, 8.1), (16.0, 16.1)]
        cuts = voice_mod.choose_cuts_by_text(silences, 20.0, [10, 30, 10])
        self.assertEqual(cuts, [(5.0, 5.8), (16.0, 16.1)])

    def test_too_few_silences_is_an_error(self):
        import voice as voice_mod

        with self.assertRaises(ValueError):
            voice_mod.choose_cuts_by_text([(1.0, 1.2)], 10.0, [5, 5, 5])


class OrientationTests(unittest.TestCase):
    def test_portrait_landscape_and_both(self):
        import media_info

        frames = [
            {"width": 1080, "height": 1920},
            {"width": 1920, "height": 1080},
            {"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]},
        ]
        self.assertEqual(media_info.labels_from_frames(frames[:1]), ["세로"])
        self.assertEqual(media_info.labels_from_frames(frames[1:2]), ["가로"])
        self.assertEqual(media_info.labels_from_frames(frames), ["세로", "가로"])

    def test_rotation_swaps_dimensions(self):
        import media_info

        self.assertEqual(media_info.orientation_label(1920, 1080, 90), "세로")


STYLE = {"provisional": True, "font": "Apple SD Gothic Neo", "font_size": 44, "frame_width": 1080,
         "side_margin": 80, "bottom_margin": 260, "char_width_factor": 1.0, "max_lines": 2}


class SubtitleTests(unittest.TestCase):
    def test_limits_follow_the_design_settings(self):
        import subtitles as subtitles_mod

        self.assertEqual(subtitles_mod.chars_per_line(STYLE), 20)
        self.assertEqual(subtitles_mod.max_chars_per_cue(STYLE), 40)
        bigger = dict(STYLE, font_size=60)
        self.assertLess(subtitles_mod.chars_per_line(bigger), 20)

    def test_cues_split_at_meaning_boundaries_and_stay_within_limit(self):
        import subtitles as subtitles_mod

        narration = "크로스나 숄더백 메면 한쪽 어깨만 계속 눌리잖아요? 예전엔 그냥 한쪽 어깨만 아프다 수준이었는데, 이제는 허리까지 아프더라고요."
        timeline = [{"no": 1, "start": 0.0, "end": 9.0, "narration": narration}]
        items = subtitles_mod.cues(timeline, STYLE)
        self.assertGreater(len(items), 1)
        self.assertTrue(items[0][2].endswith("?"))  # 질문에서 끊긴다
        for start, end, text in items:
            self.assertLessEqual(len(text.replace(" ", "")), 40)
            self.assertLess(start, end)
        self.assertEqual(items[0][0], 0.0)
        self.assertEqual(items[-1][1], 9.0)

    def test_pause_is_not_inside_a_cue(self):
        import subtitles as subtitles_mod

        timeline = [{"no": 1, "start": 0.0, "end": 2.0, "narration": "가나다."},
                    {"no": 2, "start": 2.3, "end": 4.0, "narration": "라마바."}]
        items = subtitles_mod.cues(timeline, STYLE)
        self.assertEqual(items[0][:2], (0.0, 2.0))
        self.assertEqual(items[1][:2], (2.3, 4.0))


class VoiceTests(unittest.TestCase):
    LINES = [
        {"no": 1, "target_start": 0, "target_end": 3, "narration": "첫 문장."},
        {"no": 2, "target_start": 3, "target_end": 5, "narration": "질문인가요?"},
        {"no": 3, "target_start": 5, "target_end": 9, "narration": "마지막."},
    ]

    def test_timeline_adds_pauses_and_question_pause(self):
        import voice as voice_mod

        timeline = voice_mod.build_timeline(self.LINES, [2.0, 1.5, 3.0], 0.3, 0.6)
        self.assertEqual(timeline[0]["start"], 0.0)
        self.assertEqual(timeline[0]["end"], 2.0)
        self.assertEqual(timeline[1]["start"], 2.3)   # 0.3초 쉼
        self.assertEqual(timeline[1]["pause_after"], 0.6)  # 질문 뒤 0.6초
        self.assertEqual(timeline[2]["start"], 4.4)   # 1.5초 + 0.6초 쉼 뒤
        self.assertEqual(timeline[2]["pause_after"], 0.0)  # 마지막 줄 뒤에는 쉼 없음

    def test_speed_command_uses_atempo(self):
        import voice as voice_mod

        cmd = voice_mod.speed_command(Path("raw.mp3"), Path("out.mp3"), 1.1)
        self.assertIn("atempo=1.1", cmd)

    def test_synthesize_sends_text_model_and_key(self):
        from unittest import mock

        import voice as voice_mod

        response = mock.MagicMock()
        response.read.return_value = b"mp3-bytes"
        response.__enter__.return_value = response
        with mock.patch.object(voice_mod.urllib.request, "urlopen", return_value=response) as opened:
            audio = voice_mod.synthesize("안녕하세요", "VOICE1", "eleven_multilingual_v2", "KEY")
        request = opened.call_args.args[0]
        self.assertEqual(audio, b"mp3-bytes")
        self.assertIn("/VOICE1", request.full_url)
        self.assertEqual(request.get_header("Xi-api-key"), "KEY")
        self.assertIn("eleven_multilingual_v2", request.data.decode("utf-8"))


class PendingClipTests(unittest.TestCase):
    def test_tagged_clips_are_skipped_and_failed_ones_retried(self):
        import reels as reels_cli

        videos = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
        clips = {"a": {"status": "tagged"}, "b": {"status": "tag_failed"}}
        pending = reels_cli.pending_clips(videos, clips, None)
        self.assertEqual([p.name for p in pending], ["b.mp4", "c.mp4"])

    def test_limit_caps_the_batch(self):
        import reels as reels_cli

        videos = [Path(f"{i}.mp4") for i in range(5)]
        self.assertEqual(len(reels_cli.pending_clips(videos, {}, 2)), 2)


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.library = base / "LIBRARY"
        self.index = base / "CLIP_INDEX"
        self.duplicates = base / "DUPLICATES"
        for folder in (self.library, self.index, self.duplicates):
            folder.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, content=b"v"):
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return path

    def plan(self, metadata_reader=no_metadata):
        import organize

        return organize.plan_organize(self.library, self.duplicates, VEXTS, PEXTS, metadata_reader)

    def test_videos_photos_and_others_are_routed(self):
        self.put("PRODUCT/20260904/VIDEO/20260904_150352.mp4", b"a")
        self.put("BTS/clip_IMG_20260905.mov", b"b")
        self.put("CAPTURE/20260906_IMG_1.heic", b"c")
        self.put("RESEARCH/memo.pdf", b"d")
        targets = {m.dst.relative_to(self.library).as_posix() for m in self.plan()}
        self.assertEqual(targets, {
            "VIDEO/20260904/20260904_150352.mp4",
            "VIDEO/20260905/20260905_clip_IMG.mov",
            "PHOTO/20260906/20260906_IMG_1.heic",
            "_UNSORTED/memo.pdf",
        })

    def test_duplicate_goes_to_duplicates_folder(self):
        self.put("PRODUCT/20260904/VIDEO/x.mp4", b"same")
        self.put("BTS/x.mp4", b"same")
        duplicates = [m for m in self.plan() if m.note.startswith("중복")]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].dst.parent, self.duplicates)

    def test_undated_photo_goes_to_no_date_folder(self):
        self.put("BTS/IMG_0001.jpg", b"p")
        moves = self.plan()
        self.assertEqual(moves[0].dst, self.library / "_NO_DATE" / "IMG_0001.jpg")

    def test_photo_date_comes_from_metadata(self):
        self.put("BTS/IMG_0002.jpg", b"p")
        moves = self.plan(lambda p: date(2026, 8, 1))
        self.assertEqual(moves[0].dst, self.library / "PHOTO" / "20260801" / "20260801_IMG_0002.jpg")

    def test_file_already_in_place_is_not_moved(self):
        self.put("VIDEO/20260904/20260904_150352.mp4")
        moves = self.plan()
        self.assertEqual(moves[0].dst, moves[0].src)

    def test_apply_moves_files_and_logs_them(self):
        import organize

        self.put("PRODUCT/20260904/VIDEO/20260904_150352.mp4", b"a")
        organize.apply_organize(self.plan(), self.index)
        self.assertTrue((self.library / "VIDEO" / "20260904" / "20260904_150352.mp4").exists())
        self.assertTrue((self.library / "PRODUCT").exists())  # 빈 폴더도 지우지 않는다
        log = json.loads((self.index / "move_log.json").read_text(encoding="utf-8"))
        self.assertEqual(len(log), 1)


class FolderRenameTests(unittest.TestCase):
    def test_hyphen_date_folders_are_renamed_and_others_are_left(self):
        import organize

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "VIDEO"
            (video / "2026-10-20").mkdir(parents=True)
            (video / "20261021").mkdir()
            (video / "_NO_DATE").mkdir()
            renames = organize.plan_folder_renames([video, Path(tmp) / "MISSING"])
            self.assertEqual([(old.name, new.name) for old, new in renames], [("2026-10-20", "20261020")])


class ProxyTests(unittest.TestCase):
    def test_proxy_mirrors_library_structure(self):
        import proxy as proxy_mod

        src = Path("/ssd/LIBRARY/VIDEO/20261020/20261020_A001.mp4")
        dst = proxy_mod.proxy_path(src, Path("/ssd/LIBRARY"), Path("/ssd/PROXY"))
        self.assertEqual(dst, Path("/ssd/PROXY/VIDEO/20261020/20261020_A001.mp4"))

    def test_ffmpeg_scales_to_height_and_keeps_aspect(self):
        import proxy as proxy_mod

        cmd = proxy_mod.ffmpeg_command(Path("in.mp4"), Path("out.mp4"), 720)
        self.assertIn("scale=-2:720", cmd)
        self.assertEqual(cmd[-1], "out.mp4")


class TaggerTests(unittest.TestCase):
    def test_quota_errors_are_detected(self):
        class ApiError(Exception):
            code = 429

        self.assertTrue(tagger.is_quota_error(ApiError("busy")))
        self.assertTrue(tagger.is_quota_error(RuntimeError("RESOURCE_EXHAUSTED: quota exceeded")))
        self.assertFalse(tagger.is_quota_error(RuntimeError("file upload failed")))

    def test_valid_tags_pass_through(self):
        tags = tagger.validate_tags({"bag_type": "백팩", "person": "사람_없음", "shot": "제품_클로즈업",
                                     "scene": "백팩 측면", "keywords": ["백팩"], "confidence": 0.9})
        self.assertEqual(tags["bag_type"], "백팩")
        self.assertFalse(tags["needs_review"])

    def test_unknown_bag_type_is_flagged(self):
        tags = tagger.validate_tags({"bag_type": "배낭", "person": "사람_없음", "confidence": 0.9})
        self.assertEqual(tags["bag_type"], "미확인")
        self.assertTrue(tags["needs_review"])

    def test_keywords_are_capped(self):
        tags = tagger.validate_tags({"bag_type": "토트백", "person": "사람_있음", "confidence": 0.9,
                                     "keywords": list("abcdefgh")})
        self.assertEqual(len(tags["keywords"]), 6)


class ClipIndexTests(unittest.TestCase):
    def test_tag_index_has_no_duplicate_clip_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp)
            clip_index.upsert_clip(index, "clip2", {"bag_type": "미확인", "person": "미확인", "needs_review": True})
            tag_index = json.loads((index / "tag_index.json").read_text(encoding="utf-8"))
            self.assertEqual(tag_index["미확인"], ["clip2"])
            self.assertEqual(tag_index["검토필요"], ["clip2"])


if __name__ == "__main__":
    unittest.main()
