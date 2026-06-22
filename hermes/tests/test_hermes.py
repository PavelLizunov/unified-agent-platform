"""Hermes unit tests (stdlib unittest, no network). Run from hermes/:  python -m unittest -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hermes  # noqa: E402


class TestParser(unittest.TestCase):
    def test_plain_block(self):
        tc = hermes.parse_tool_call('```tool_call\n{"name":"calc","arguments":{"expression":"1+1"}}\n```')
        self.assertEqual(tc["name"], "calc")
        self.assertEqual(tc["arguments"]["expression"], "1+1")

    def test_block_with_prose_around(self):
        text = 'Let me compute that.\n```tool_call\n{"name":"now","arguments":{}}\n```\nthanks'
        self.assertEqual(hermes.parse_tool_call(text)["name"], "now")

    def test_no_block_is_none(self):
        self.assertIsNone(hermes.parse_tool_call("just a final answer, no tools"))

    def test_unlabeled_fence(self):
        self.assertEqual(hermes.parse_tool_call('```\n{"name":"calc","arguments":{}}\n```')["name"], "calc")

    def test_trailing_comma_repair(self):
        tc = hermes.parse_tool_call('```tool_call\n{"name":"calc","arguments":{"expression":"2",},}\n```')
        self.assertEqual(tc["name"], "calc")

    def test_missing_name_is_none(self):
        self.assertIsNone(hermes.parse_tool_call('```tool_call\n{"arguments":{}}\n```'))

    def test_non_dict_args_normalised(self):
        tc = hermes.parse_tool_call('```tool_call\n{"name":"now","arguments":"oops"}\n```')
        self.assertEqual(tc["arguments"], {})


class TestCalc(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(hermes.tool_calc({"expression": "48271*99173"}), str(48271 * 99173))

    def test_parens_and_div(self):
        self.assertEqual(hermes.tool_calc({"expression": "2*(3+4)"}), "14")
        self.assertEqual(hermes.tool_calc({"expression": "10/4"}), "2.5")

    def test_blocks_huge_exponent(self):
        self.assertTrue(hermes.tool_calc({"expression": "9**99999"}).startswith("error"))

    def test_blocks_code_injection(self):
        self.assertTrue(hermes.tool_calc({"expression": "__import__('os').system('id')"}).startswith("error"))
        self.assertTrue(hermes.tool_calc({"expression": "open('/etc/passwd')"}).startswith("error"))


class TestHttpGuard(unittest.TestCase):
    def test_scheme(self):
        self.assertTrue(hermes.tool_http_get({"url": "ftp://x/y"}).startswith("error"))
        self.assertTrue(hermes.tool_http_get({"url": "file:///etc/passwd"}).startswith("error"))

    def test_ssrf_loopback(self):
        self.assertIn("blocked", hermes.tool_http_get({"url": "http://127.0.0.1/"}))

    def test_ssrf_metadata(self):
        self.assertIn("blocked", hermes.tool_http_get({"url": "http://169.254.169.254/latest/meta-data/"}))

    def test_ssrf_cluster_dns(self):
        # kubernetes.default.svc resolves to a ClusterIP (private) → blocked, or DNS error → still error
        self.assertTrue(hermes.tool_http_get({"url": "http://10.0.0.1/"}).startswith("error"))


class TestNow(unittest.TestCase):
    def test_iso(self):
        self.assertRegex(hermes.tool_now({}), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class _MockModel:
    """Returns scripted assistant outputs in order; records the messages it saw."""
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, messages, model=None, reasoning_effort=None, timeout=None):
        self.calls.append(messages)
        return self.outputs.pop(0) if self.outputs else "fallback final"


class TestReact(unittest.TestCase):
    def setUp(self):
        self._orig = hermes.call_model

    def tearDown(self):
        hermes.call_model = self._orig

    def test_single_tool_then_final(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"calc","arguments":{"expression":"6*7"}}\n```',
            "The answer is 42.",
        ])
        final, trace = hermes.run_react("what is 6*7")
        self.assertEqual(final, "The answer is 42.")
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["tool"], "calc")
        self.assertEqual(trace[0]["result"], "42")

    def test_no_tool_immediate_final(self):
        hermes.call_model = _MockModel(["Hello, no tools needed."])
        final, trace = hermes.run_react("hi")
        self.assertEqual(final, "Hello, no tools needed.")
        self.assertEqual(trace, [])

    def test_unknown_tool_is_reported_not_crashed(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"rm_rf","arguments":{}}\n```',
            "ok, can't do that",
        ])
        final, trace = hermes.run_react("delete everything")
        self.assertIn("unknown tool", trace[0]["result"])
        self.assertEqual(final, "ok, can't do that")

    def test_chained_two_tools(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"now","arguments":{}}\n```',
            '```tool_call\n{"name":"calc","arguments":{"expression":"2+2"}}\n```',
            "done",
        ])
        final, trace = hermes.run_react("chain")
        self.assertEqual(len(trace), 2)
        self.assertEqual(final, "done")

    def test_repeated_call_is_cached_then_model_answers(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"now","arguments":{}}\n```',
            '```tool_call\n{"name":"now","arguments":{}}\n```',  # repeat -> cached, loop continues
            "the time is X",
        ])
        final, _trace = hermes.run_react("time?")
        self.assertEqual(final, "the time is X")

    def test_repeated_loop_breaks_and_summarizes(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"now","arguments":{}}\n```',
            '```tool_call\n{"name":"now","arguments":{}}\n```',  # repeat 1 (cached)
            '```tool_call\n{"name":"now","arguments":{}}\n```',  # repeat 2 -> break -> summarize
            "summarized answer",
        ])
        final, _ = hermes.run_react("time?")
        self.assertEqual(final, "summarized answer")  # single-shot summary, never loops forever

    def test_max_steps_then_summarizes(self):
        # distinct args -> no dedup -> loop caps at max_steps, then one summarization call
        hermes.call_model = _MockModel(
            ['```tool_call\n{"name":"calc","arguments":{"expression":"%d+1"}}\n```' % i for i in range(3)]
            + ["final summary from data"]
        )
        final, trace = hermes.run_react("loop", max_steps=3)
        self.assertEqual(len(trace), 3)
        self.assertEqual(final, "final summary from data")


class TestSlash(unittest.TestCase):
    def test_help_tools_model(self):
        self.assertIn("/tools", hermes.handle_slash("/help"))
        self.assertIn("calc", hermes.handle_slash("/tools"))
        self.assertIn("model", hermes.handle_slash("/model").lower())

    def test_unknown_slash(self):
        self.assertIsNone(hermes.handle_slash("/nonsense"))


class TestRegistry(unittest.TestCase):
    def test_list_tools_text(self):
        t = hermes.list_tools_text()
        for name in ("calc", "now", "http_get", "kube_pods"):
            self.assertIn(name, t)


class TestAuthz(unittest.TestCase):
    def setUp(self):
        self._k, self._sk, self._dev = hermes.HERMES_KEY, hermes.SCOPED_KEYS, hermes.DEVMODE
        hermes.HERMES_KEY = "master"
        hermes.SCOPED_KEYS = {"ro": frozenset({"read"})}
        hermes.DEVMODE = False

    def tearDown(self):
        hermes.HERMES_KEY, hermes.SCOPED_KEYS, hermes.DEVMODE = self._k, self._sk, self._dev

    def test_master_grants_all_scopes(self):
        self.assertEqual(hermes.resolve_scopes("Bearer master"), hermes.ALL_SCOPES)

    def test_scoped_key_subset(self):
        self.assertEqual(hermes.resolve_scopes("Bearer ro"), frozenset({"read"}))

    def test_unknown_key_is_none(self):
        self.assertIsNone(hermes.resolve_scopes("Bearer nope"))

    def test_missing_header_is_none(self):
        self.assertIsNone(hermes.resolve_scopes(""))


class TestAuthzGating(unittest.TestCase):
    def setUp(self):
        self._o = hermes.call_model

    def tearDown(self):
        hermes.call_model = self._o

    def test_net_tool_blocked_for_read_only_key(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"http_get","arguments":{"url":"http://example.com"}}\n```',
            "ok",
        ])
        _final, trace = hermes.run_react("fetch", allowed_scopes=frozenset({"read"}))
        self.assertIn("not authorized", trace[0]["result"])

    def test_in_scope_tool_runs(self):
        hermes.call_model = _MockModel([
            '```tool_call\n{"name":"now","arguments":{}}\n```',
            "the time",
        ])
        _final, trace = hermes.run_react("time", allowed_scopes=frozenset({"compute"}))
        self.assertNotIn("not authorized", trace[0]["result"])


class TestScopeFilter(unittest.TestCase):
    def test_read_only_key_sees_only_read_tools(self):
        t = hermes.list_tools_text(frozenset({"read"}))
        self.assertIn("kube_pods", t)
        self.assertIn("kube_logs", t)
        self.assertNotIn("http_get", t)
        self.assertNotIn("calc", t)


class TestNewTools(unittest.TestCase):
    def test_kube_get_rejects_unknown_kind(self):
        self.assertTrue(hermes.tool_kube_get({"kind": "secrets"}).startswith("error"))

    def test_kube_logs_validates_pod_name(self):
        self.assertTrue(hermes.tool_kube_logs({"namespace": "x", "pod": "bad pod!"}).startswith("error"))

    def test_http_post_ssrf_and_scheme(self):
        self.assertIn("blocked", hermes.tool_http_post({"url": "http://127.0.0.1/", "body": "x"}))
        self.assertTrue(hermes.tool_http_post({"url": "ftp://x/y", "body": "x"}).startswith("error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
