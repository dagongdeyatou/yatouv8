from __future__ import annotations

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("live_runner.py")
SPEC = importlib.util.spec_from_file_location("google_vm_live_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class HeaderBag(dict[str, str]):
    def get_list(self, name: str) -> list[str]:
        value = self.get(name)
        return [value] if value else []


class Response:
    def __init__(self, *, status: int, url: str, text: str, set_cookie: str | None = None) -> None:
        self.status_code = status
        self.url = url
        self.text = text
        self.headers = HeaderBag()
        self.history = []
        if set_cookie:
            self.headers["set-cookie"] = set_cookie


class GoogleVmLiveRunnerTests(unittest.TestCase):
    def test_headers_do_not_inherit_curl_mac_identity(self) -> None:
        headers = runner.browser_headers(referer="https://www.google.com/")

        self.assertIn("Chrome/150", headers["user-agent"])
        self.assertEqual(headers["sec-ch-ua-platform"], '"Windows"')
        self.assertEqual(headers["sec-fetch-site"], "same-origin")

    def test_result_page_requires_search_container_and_heading(self) -> None:
        valid = Response(
            status=200,
            url="https://www.google.com/search?q=yatouv8&sei=x",
            text='<main id="search"><div id="rso"><h3>yatouv8</h3></div></main>',
        )
        sorry = Response(
            status=429,
            url="https://www.google.com/sorry/index?continue=x",
            text="unusual traffic from your computer network",
        )

        self.assertTrue(runner.response_markers(valid)["result_dom"])
        self.assertFalse(runner.response_markers(valid)["sorry"])
        self.assertTrue(runner.response_markers(sorry)["sorry"])
        self.assertFalse(runner.response_markers(sorry)["result_dom"])

    def test_cookie_consumption_accepts_redirect_set_cookie_zero(self) -> None:
        redirect = Response(
            status=302,
            url="https://www.google.com/search?q=x&sei=y",
            text="",
            set_cookie="SG_SS=0; Path=/; Secure; SameSite=None",
        )
        final = Response(
            status=200,
            url="https://www.google.com/search?q=x&sei=y",
            text='<div id="search"><h3>x</h3></div>',
        )
        final.history = [redirect]

        self.assertTrue(runner.sg_ss_consumed(final, [], hostname="www.google.com"))

    def test_token_evidence_is_redacted(self) -> None:
        record = runner.redacted_token(
            {"name": "SG_SS", "value": "*secret", "domain": "www.google.com", "path": "/"}
        )

        self.assertNotIn("value", record)
        self.assertEqual(record["value_prefix"], "*")
        self.assertEqual(record["value_length"], 7)
        self.assertEqual(len(record["value_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
