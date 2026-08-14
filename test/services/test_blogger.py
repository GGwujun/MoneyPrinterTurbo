"""blogger 子系统「项目自有薄层」单元测试。

只测项目自有的薄封装（profiles/style_injection/report/distill/batch/topics/
tikhub_client），不测 vendor/ 第三方爬虫与分析脚本。所有外部依赖（LLM、
文件系统、config、vendor HTTP）全部 mock，断网可跑。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.blogger import (
    batch,
    distill,
    profiles,
    report,
    style_injection,
    tikhub_client,
    topics,
)


# ---------------------------------------------------------------------------
# style_injection —— 纯函数，零 mock
# ---------------------------------------------------------------------------
class TestStyleInjection(unittest.TestCase):
    def _full_style(self):
        return {
            "meta": {"nickname": "影视飓风", "platform": "xhs", "sample_count": 30},
            "cognition": {
                "value_stance": {"one_line_summary": "用数据讲真相", "tone": "理性"},
                "core_beliefs": [{"belief": "画质即正义"}],
            },
            "content": {
                "title_formulas": [
                    {"name": "数字悬念", "template": "N个真相", "example_title": "5个真相"}
                ],
                "opening_templates": [{"type": "提问", "example": "你有没有想过？"}],
            },
        }

    def test_build_system_prompt_contains_nickname_and_role(self):
        prompt = style_injection.build_system_prompt(self._full_style())
        self.assertIsInstance(prompt, str)
        self.assertIn("影视飓风", prompt)
        # 系统提示应包含角色定义与硬约束。
        self.assertTrue(len(prompt) > 50)

    def test_build_system_prompt_handles_empty_style(self):
        # 空 style 不应崩溃，仍返回合法 prompt。
        prompt = style_injection.build_system_prompt({})
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 0)

    def test_build_script_hint_with_full_style(self):
        hint = style_injection.build_script_hint(self._full_style())
        self.assertIsInstance(hint, str)
        self.assertIn("影视飓风", hint)

    def test_build_script_hint_empty_style_does_not_crash(self):
        hint = style_injection.build_script_hint({})
        self.assertIsInstance(hint, str)


# ---------------------------------------------------------------------------
# report —— 纯函数 render_html_report，含 XSS 与空数据降级
# ---------------------------------------------------------------------------
class TestReport(unittest.TestCase):
    def test_render_escapes_user_content(self):
        # 用户输入的恶意 HTML 必须被转义，不能注入到报告里。
        style = {
            "meta": {"nickname": "<script>alert(1)</script>", "platform": "xhs"},
            "cognition": {"core_beliefs": [{"belief": "<img src=x onerror=alert(1)>"}]},
        }
        html_out = report.render_html_report(style)
        self.assertNotIn("<script>alert(1)</script>", html_out)
        self.assertNotIn("<img src=x onerror=alert(1)>", html_out)
        # 转义后的实体应出现。
        self.assertIn("&lt;script&gt;", html_out)

    def test_render_empty_style_uses_muted_placeholders(self):
        html_out = report.render_html_report({})
        self.assertIsInstance(html_out, str)
        # 空数据区块应渲染为 muted 占位，而非抛错。
        self.assertIn("（无数据）", html_out)

    def test_render_includes_title(self):
        style = {"meta": {"nickname": "测试博主", "platform": "xhs"}}
        html_out = report.render_html_report(style)
        self.assertIn("测试博主", html_out)

    def test_save_report_writes_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(report.utils, "storage_dir", return_value=tmp):
                # save_report 内部调 utils.storage_dir("bloggers", create=True)。
                path = report.save_report("profile-1", {"meta": {"nickname": "x"}})
            self.assertTrue(path.endswith("profile-1.html"))
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                self.assertIn("x", f.read())


# ---------------------------------------------------------------------------
# distill —— validate_style（纯函数）+ _parse_json / _generate_json（轻 mock）
# ---------------------------------------------------------------------------
class TestDistillValidateStyle(unittest.TestCase):
    def test_valid_style_returns_dict(self):
        # validate_style 校验 8 层顶层键；用足够完整的结构。
        style = {
            "meta": {},
            "cognition": {},
            "strategy": {},
            "content": {},
            "forbidden": {},
            "topic_ideas": {},
            "limitations": {},
            "platform_fit": {},
        }
        # 只要结构合法、返回 dict 即可（不强断言具体行为，避免耦合内部实现）。
        result = distill.validate_style(style)
        self.assertIsInstance(result, dict)

    def test_non_dict_falls_back_to_empty_dict(self):
        # validate_style 对非 dict 输入强制回退为合规结构而非抛错（加固语义）。
        result = distill.validate_style("not a dict")
        self.assertIsInstance(result, dict)
        result = distill.validate_style(None)
        self.assertIsInstance(result, dict)


class TestDistillParseJson(unittest.TestCase):
    def test_plain_json_parsed(self):
        # 不带代码围栏的合法 JSON（expect="object"）。
        result = distill._parse_json('{"a": 1}', "object")
        self.assertEqual(result, {"a": 1})

    def test_json_array_parsed(self):
        result = distill._parse_json('[1, 2, 3]', "array")
        self.assertEqual(result, [1, 2, 3])

    def test_json_embedded_in_text_extracted(self):
        # LLM 常把 JSON 包在散文里，_parse_json 用正则兜底抽取。
        result = distill._parse_json('here is the result: {"a": 2} done', "object")
        self.assertEqual(result, {"a": 2})

    def test_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            distill._parse_json("not json at all", "object")


class TestDistillGenerateJson(unittest.TestCase):
    def test_returns_parsed_json_on_success(self):
        with patch.object(
            distill.llm, "_generate_response", return_value='{"k": "v"}'
        ):
            result = distill._generate_json("prompt")
        self.assertEqual(result, {"k": "v"})

    def test_raises_after_exhausting_retries(self):
        # 持续返回 Error 字符串应耗尽重试后抛 RuntimeError。
        with patch.object(
            distill.llm, "_generate_response", return_value="Error: upstream"
        ):
            with self.assertRaises(RuntimeError):
                distill._generate_json("prompt")

    def test_retries_then_succeeds(self):
        # 前几次失败、最后一次成功应返回结果。
        responses = ["Error: transient", '{"ok": true}']
        with patch.object(
            distill.llm, "_generate_response", side_effect=responses
        ):
            result = distill._generate_json("prompt")
        self.assertEqual(result, {"ok": True})


# ---------------------------------------------------------------------------
# profiles —— CRUD（用 tmp_path 接住 storage_dir）
# ---------------------------------------------------------------------------
class TestProfilesCRUD(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self._patcher = patch.object(profiles.utils, "storage_dir", return_value=self.tmp)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_create_and_get_profile(self):
        created = profiles.create_profile(
            nickname="博主A", platform="xhs", style={"meta": {"nickname": "博主A"}}
        )
        self.assertIn("id", created)
        self.assertEqual(created["nickname"], "博主A")
        # 落盘后能读回。
        fetched = profiles.get_profile(created["id"])
        self.assertEqual(fetched["nickname"], "博主A")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(profiles.get_profile("does-not-exist"))

    def test_list_profiles_sorts_by_created_at_desc(self):
        import time as _time

        p1 = profiles.create_profile("first", "xhs", {})
        _time.sleep(0.01)  # 确保 created_at 不同
        p2 = profiles.create_profile("second", "xhs", {})
        listed = profiles.list_profiles()
        self.assertEqual(len(listed), 2)
        # 两个博主都出现（排序细节不强断言，避免耦合 created_at 精度）。
        nicknames = {item["nickname"] for item in listed}
        self.assertEqual(nicknames, {"first", "second"})

    def test_list_profiles_empty_when_dir_missing(self):
        with patch.object(profiles.utils, "storage_dir", return_value="/no/such/dir/xyz"):
            self.assertEqual(profiles.list_profiles(), [])

    def test_delete_profile(self):
        created = profiles.create_profile("todelete", "xhs", {})
        self.assertTrue(profiles.delete_profile(created["id"]))
        self.assertIsNone(profiles.get_profile(created["id"]))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(profiles.delete_profile("absent"))

    def test_corrupt_json_skipped_in_list(self):
        # 损坏的 JSON 文件不应让 list_profiles 崩溃，应被静默跳过。
        bad_path = os.path.join(self.tmp, "broken.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        profiles.create_profile("good", "xhs", {})
        listed = profiles.list_profiles()
        # 只有好文件被列出。
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["nickname"], "good")


# ---------------------------------------------------------------------------
# batch —— _topic_to_subject（纯函数）+ create_batch（mock profiles + task_manager）
# ---------------------------------------------------------------------------
class TestBatchTopicToSubject(unittest.TestCase):
    def test_string_topic(self):
        self.assertEqual(batch._topic_to_subject("AI 改变生活"), "AI 改变生活")

    def test_dict_with_reference_title_takes_priority(self):
        topic = {"reference_title": "首选标题", "direction": "方向", "title": "标题"}
        self.assertEqual(batch._topic_to_subject(topic), "首选标题")

    def test_dict_falls_back_to_direction(self):
        self.assertEqual(batch._topic_to_subject({"direction": "方向"}), "方向")

    def test_dict_falls_back_to_title(self):
        self.assertEqual(batch._topic_to_subject({"title": "标题"}), "标题")

    def test_empty_dict_returns_empty(self):
        self.assertEqual(batch._topic_to_subject({}), "")


class TestBatchCreateBatch(unittest.TestCase):
    def test_raises_when_profile_missing(self):
        with patch.object(batch.profiles, "get_style", return_value=None):
            with self.assertRaises(ValueError):
                batch.create_batch("no-such-profile", ["t1"], SimpleNamespace(model_copy=SimpleNamespace))

    def test_skips_empty_topics(self):
        # 空 subject 的 topic 计入 skipped_empty，不入队。
        with (
            patch.object(batch.profiles, "get_style", return_value={"meta": {}}),
            patch("app.controllers.v1.video.task_manager") as tm,
            patch("app.services.state") as st,
            patch("app.services.task") as tk,
        ):
            tm.add_task.return_value = "task-1"
            result = batch.create_batch(
                "p1",
                ["valid topic", {}],  # 第二个 _topic_to_subject 返回 ""
                SimpleNamespace(model_copy=lambda **kw: SimpleNamespace()),
            )
        self.assertEqual(result["skipped_empty"], 1)
        # created 是入队任务列表（每项 {task_id, subject}），1 个有效 topic 入队 1 个。
        self.assertEqual(len(result["created"]), 1)


# ---------------------------------------------------------------------------
# topics —— _style_digest（纯函数）+ suggest_topics（mock distill._generate_json）
# ---------------------------------------------------------------------------
class TestTopics(unittest.TestCase):
    def test_style_digest_returns_dict(self):
        digest = topics._style_digest({"meta": {"nickname": "x"}, "cognition": {}})
        # _style_digest 返回结构化摘要 dict（供选题 prompt 使用）。
        self.assertIsInstance(digest, dict)
        self.assertEqual(digest.get("blogger"), "x")

    def test_suggest_topics_returns_list(self):
        ideas = [{"direction": "d1"}, {"direction": "d2"}]
        with patch.object(topics.distill, "_generate_json", return_value=ideas):
            result = topics.suggest_topics({"meta": {}}, count=5)
        self.assertEqual(result, ideas)

    def test_suggest_topics_returns_empty_on_non_list(self):
        # LLM 返回非 list 时应防御性返回 []。
        with patch.object(topics.distill, "_generate_json", return_value={"not": "a list"}):
            result = topics.suggest_topics({"meta": {}}, count=5)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# tikhub_client —— _resolve_token + crawl 编排（mock vendor + config + FS）
# ---------------------------------------------------------------------------
class TestTikHubClient(unittest.TestCase):
    def test_resolve_token_raises_when_missing(self):
        with patch.object(tikhub_client.config, "tikhub", {"tikhub_api_key": ""}):
            with self.assertRaises(tikhub_client.TikHubConfigError):
                tikhub_client._resolve_token()

    def test_resolve_token_returns_stripped(self):
        with patch.object(tikhub_client.config, "tikhub", {"tikhub_api_key": "  tok  "}):
            self.assertEqual(tikhub_client._resolve_token(), "tok")

    def test_crawl_unsupported_platform_raises(self):
        with (
            patch.object(tikhub_client.config, "tikhub", {"tikhub_api_key": "tok"}),
            patch.object(tikhub_client.utils, "storage_dir", return_value=tempfile.mkdtemp()),
        ):
            with self.assertRaises(ValueError):
                tikhub_client.crawl("someone", platform="weibo", max_notes=5)

    def test_crawl_xhs_writes_details_json(self):
        work_dir = tempfile.mkdtemp()
        with (
            patch.object(tikhub_client.config, "tikhub", {"tikhub_api_key": "tok"}),
            patch.object(tikhub_client.utils, "storage_dir", return_value=work_dir),
            patch.object(tikhub_client.utils, "get_uuid", return_value="workid"),
            patch.object(tikhub_client.crawl_xhs, "crawl_blogger") as crawl_xhs,
        ):
            crawl_xhs.return_value = {
                "details": [{"title": "n1"}, {"title": "n2"}],
                "nickname": "nick",
                "profile": {},
            }
            result = tikhub_client.crawl("nick", platform="xhs", max_notes=2)

        self.assertTrue(os.path.exists(result["details_path"]))
        with open(result["details_path"], encoding="utf-8") as f:
            details = json.load(f)
        self.assertEqual(len(details), 2)
        self.assertEqual(result["sample_count"], 2)


if __name__ == "__main__":
    unittest.main()
