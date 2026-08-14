"""app/utils/utils.py 中被广泛复用的纯函数的单元测试。

这些函数此前只被其它测试间接覆盖，缺乏独立回归网。这里针对边界条件
（空串、纯标点、多语言、非法数值、None 输入等）单独验证。
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils


class TestNormalizeClipSpeed(unittest.TestCase):
    def test_normal_value_is_clamped_to_range(self):
        self.assertEqual(utils.normalize_clip_speed(1.0), 1.0)
        self.assertEqual(utils.normalize_clip_speed(1.5), 1.5)

    def test_below_min_clamps_to_min(self):
        self.assertEqual(utils.normalize_clip_speed(0.1), 0.5)

    def test_above_max_clamps_to_max(self):
        self.assertEqual(utils.normalize_clip_speed(5.0), 2.0)

    def test_string_numeric_is_parsed(self):
        self.assertEqual(utils.normalize_clip_speed("1.5"), 1.5)

    def test_invalid_string_falls_back_to_default(self):
        self.assertEqual(utils.normalize_clip_speed("fast"), 1.0)
        self.assertEqual(utils.normalize_clip_speed("fast", default=0.8), 0.8)

    def test_none_falls_back_to_default(self):
        self.assertEqual(utils.normalize_clip_speed(None), 1.0)

    def test_non_finite_falls_back_to_default(self):
        self.assertEqual(utils.normalize_clip_speed(float("nan")), 1.0)
        self.assertEqual(utils.normalize_clip_speed(float("inf")), 1.0)
        self.assertEqual(utils.normalize_clip_speed(float("-inf")), 1.0)

    def test_zero_and_negative_fall_back_to_default(self):
        self.assertEqual(utils.normalize_clip_speed(0), 1.0)
        self.assertEqual(utils.normalize_clip_speed(-1.0), 1.0)


class TestParseExtension(unittest.TestCase):
    def test_simple_extension(self):
        self.assertEqual(utils.parse_extension("video.mp4"), "mp4")

    def test_uppercase_is_lowercased(self):
        self.assertEqual(utils.parse_extension("VIDEO.MP4"), "mp4")

    def test_double_extension(self):
        self.assertEqual(utils.parse_extension("archive.tar.gz"), "gz")

    def test_no_extension_returns_empty(self):
        self.assertEqual(utils.parse_extension("README"), "")

    def test_dotfile_has_no_extension(self):
        # Path 把 ".gitignore" 视为无扩展名文件（suffix 为 ""），这里锁定现行行为。
        self.assertEqual(utils.parse_extension(".gitignore"), "")


class TestTimeConvertSecondsToHmsm(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(utils.time_convert_seconds_to_hmsm(0), "00:00:00,000")

    def test_subsecond(self):
        self.assertEqual(utils.time_convert_seconds_to_hmsm(0.5), "00:00:00,500")

    def test_minutes_and_seconds(self):
        # 1 分 2.5 秒 = 62.5 秒
        self.assertEqual(utils.time_convert_seconds_to_hmsm(62.5), "00:01:02,500")

    def test_hours(self):
        # 1 小时 2 分 3 秒 = 3723 秒
        self.assertEqual(utils.time_convert_seconds_to_hmsm(3723), "01:02:03,000")

    def test_millisecond_rounding_truncates(self):
        # 1.2349 秒 -> 1234 ms (int 截断，非四舍五入)
        self.assertEqual(utils.time_convert_seconds_to_hmsm(1.2349), "00:00:01,234")


class TestTextToSrt(unittest.TestCase):
    def test_basic_srt_block(self):
        srt = utils.text_to_srt(1, "hello world", 0.0, 1.5)
        # 每块以序号、时间轴、正文组成。
        self.assertIn("1\n", srt)
        self.assertIn("00:00:00,000 --> 00:00:01,500", srt)
        self.assertIn("hello world", srt)

    def test_index_is_used(self):
        srt = utils.text_to_srt(7, "x", 0.0, 1.0)
        self.assertTrue(srt.lstrip().startswith("7"))


class TestStrContainsPunctuation(unittest.TestCase):
    def test_contains_punctuation(self):
        self.assertTrue(utils.str_contains_punctuation("hello,world"))
        self.assertTrue(utils.str_contains_punctuation("end."))

    def test_no_punctuation(self):
        self.assertFalse(utils.str_contains_punctuation("helloworld"))
        self.assertFalse(utils.str_contains_punctuation(""))


class TestSplitStringByPunctuations(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(utils.split_string_by_punctuations(""), [])

    def test_no_punctuation_returns_single_chunk(self):
        self.assertEqual(utils.split_string_by_punctuations("hello world"), ["hello world"])

    def test_splits_on_comma(self):
        self.assertEqual(
            utils.split_string_by_punctuations("a, b, c"),
            ["a", "b", "c"],
        )

    def test_splits_on_period(self):
        self.assertEqual(
            utils.split_string_by_punctuations("first. second."),
            ["first", "second"],
        )

    def test_newline_is_a_split_marker(self):
        self.assertEqual(
            utils.split_string_by_punctuations("line one\nline two"),
            ["line one", "line two"],
        )

    def test_decimal_dot_not_split(self):
        # "2.5" 中的小数点不应断句。
        self.assertEqual(
            utils.split_string_by_punctuations("fee is 2.5 percent"),
            ["fee is 2.5 percent"],
        )

    def test_thousands_comma_not_split(self):
        # "1,000" 的千分位逗号不应断句。
        self.assertEqual(
            utils.split_string_by_punctuations("about 1,000 years ago"),
            ["about 1,000 years ago"],
        )

    def test_empty_chunks_filtered(self):
        # 连续标点不应产生空串片段。
        self.assertEqual(
            utils.split_string_by_punctuations("a,,,b"),
            ["a", "b"],
        )


class TestNormalizeScriptForSubtitleMatching(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(utils.normalize_script_for_subtitle_matching(None), "")

    def test_empty_string(self):
        self.assertEqual(utils.normalize_script_for_subtitle_matching(""), "")

    def test_underscores_removed(self):
        # 下划线格式符号不应进入字幕匹配。
        result = utils.normalize_script_for_subtitle_matching("hello_world_end")
        self.assertNotIn("_", result)
        self.assertEqual(result, "helloworldend")

    def test_markdown_separator_lines_removed(self):
        script = "intro\n---\nbody\n***\nend"
        result = utils.normalize_script_for_subtitle_matching(script)
        self.assertNotIn("---", result.splitlines())
        self.assertNotIn("***", result.splitlines())
        self.assertEqual(result, "intro\nbody\nend")

    def test_preserves_normal_lines(self):
        script = "first paragraph\nsecond paragraph"
        self.assertEqual(
            utils.normalize_script_for_subtitle_matching(script),
            "first paragraph\nsecond paragraph",
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            utils.normalize_script_for_subtitle_matching("  hello  \n  world  "),
            "hello\nworld",
        )


if __name__ == "__main__":
    unittest.main()
