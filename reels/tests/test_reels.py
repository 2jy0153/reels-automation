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

EXTS = [".mp4", ".mov"]
FIXTURE = Path(__file__).parent / "fixtures" / "script_v3.md"


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox = base / "INBOX"
        self.footage = base / "FOOTAGE"
        self.duplicates = base / "DUPLICATES"
        self.index = base / "CLIP_INDEX"
        for folder in (self.inbox, self.footage, self.duplicates, self.index):
            folder.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, content=b"video", mtime=None):
        path = self.inbox / name
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_skips_macos_metadata_and_non_video(self):
        self.make("._20260906_094555.mp4")
        self.make(".DS_Store")
        self.assertFalse(ingest.is_video(self.inbox / "._20260906_094555.mp4", EXTS))
        self.assertFalse(ingest.is_video(self.inbox / ".DS_Store", EXTS))
        self.assertTrue(ingest.is_video(self.make("clip.MP4"), EXTS))

    def test_name_is_date_then_original_name_when_no_date_in_name(self):
        self.assertEqual(ingest.new_name(Path("A001_09222312_C006.MP4"), date(2026, 9, 22)),
                         "20260922_A001_09222312_C006.mp4")

    def test_date_inside_name_is_moved_to_front_once(self):
        self.assertEqual(ingest.new_name(Path("20260904_150352.mp4"), date(2026, 9, 4)), "20260904_150352.mp4")
        self.assertEqual(ingest.new_name(Path("IMG_20260904_150352.mp4"), date(2026, 9, 4)),
                         "20260904_IMG_150352.mp4")
        self.assertEqual(ingest.new_name(Path("A001_20260922_C006.mp4"), date(2026, 9, 22)),
                         "20260922_A001_C006.mp4")

    def test_date_from_filename_and_camera_code_is_not_a_date(self):
        self.assertEqual(ingest.recording_date(Path("20260904_150352.mp4")), date(2026, 9, 4))
        path = self.make("A001_09222312_C006.mp4", mtime=1_700_000_000)
        self.assertEqual(ingest.recording_date(path), date.fromtimestamp(1_700_000_000))

    def make_in(self, folder_name, name, content):
        folder = self.inbox / folder_name
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return path

    def test_same_name_and_size_in_one_batch_keeps_first_only(self):
        first = self.make_in("a", "20260904_150352.mp4", b"abc")
        second = self.make_in("b", "20260904_150352.mp4", b"abc")
        plans = ingest.plan_ingest([first, second], self.footage, self.index)
        self.assertIsNotNone(plans[0].dst)
        self.assertIsNone(plans[1].dst)

    def test_same_name_different_size_is_kept_with_suffix(self):
        a = self.make_in("a", "x.mp4", b"abc")
        b = self.make_in("b", "x.mp4", b"abcdef")
        plans = ingest.plan_ingest([a, b], self.footage, self.index)
        self.assertIsNotNone(plans[0].dst)
        self.assertIsNotNone(plans[1].dst)
        self.assertNotEqual(plans[0].dst, plans[1].dst)

    def test_run_moves_verified_copy_and_records_log(self):
        src = self.make("20260904_150352.mp4", b"abc")
        plans = ingest.plan_ingest([src], self.footage, self.index)
        ingest.run_plan(plans, self.duplicates, self.index)
        final = self.footage / "2026-09-04" / "20260904_150352.mp4"
        self.assertEqual(final.read_bytes(), b"abc")
        self.assertFalse(src.exists())
        log = ingest.load_log(self.index)
        self.assertEqual(log[0]["original_name"], "20260904_150352.mp4")
        self.assertEqual(log[0]["size"], 3)

    def test_already_ingested_file_becomes_duplicate_on_next_run(self):
        first = self.make("20260904_150352.mp4", b"abc")
        ingest.run_plan(ingest.plan_ingest([first], self.footage, self.index), self.duplicates, self.index)

        again = self.make("20260904_150352.mp4", b"abc")
        plans = ingest.plan_ingest([again], self.footage, self.index)
        self.assertIsNone(plans[0].dst)
        ingest.run_plan(plans, self.duplicates, self.index)
        self.assertTrue((self.duplicates / "20260904_150352.mp4").exists())
        self.assertEqual(len(list(self.footage.rglob("*.mp4"))), 1)

    def test_no_overwrite_when_destination_exists(self):
        (self.footage / "2026-09-04").mkdir()
        (self.footage / "2026-09-04" / "20260904_150352.mp4").write_bytes(b"old")
        src = self.make("20260904_150352.mp4", b"newer-content")
        plans = ingest.plan_ingest([src], self.footage, self.index)
        self.assertEqual(plans[0].dst.name, "20260904_150352_2.mp4")


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.data = script.parse_script(FIXTURE.read_text(encoding="utf-8"), "2026-10-19_backpack_01")

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

    def test_plain_text_without_table_is_rejected(self):
        with self.assertRaises(ValueError):
            script.parse_script("그냥 글입니다.", "x")

    def test_end_before_start_is_error(self):
        errors, _ = script.check_script({"lines": [
            {"no": 1, "target_start": 5, "target_end": 3, "narration": "가", "caption": None}]})
        self.assertTrue(errors)


class TaggerTests(unittest.TestCase):
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
