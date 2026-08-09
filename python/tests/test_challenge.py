from __future__ import annotations

import datetime
import unittest

import yatouv8


class Response:
    def __init__(self, html: str) -> None:
        self.url = "https://www.google.com/search?q=yatouv8"
        self.status_code = 200
        self.text = html
        self.content = html.encode()
        self.elapsed = datetime.timedelta(milliseconds=125)
        self.infos = {}


def challenge_html(*scripts: str) -> str:
    return "<!doctype html>" + "".join(f"<script>{source}</script>" for source in scripts)


class ChallengeApiTests(unittest.TestCase):
    def test_solve_returns_stateless_request_bundle(self) -> None:
        response = Response(
            challenge_html(
                "globalThis.seed=1",
                "globalThis.seed+=1",
                "document.cookie='SG_SS=*fixture; Path=/; Secure; SameSite=None'",
                "location.replace(location.href+'&sei=fixture')",
            )
        )

        bundle = yatouv8.solve_with_yatouv8(
            response,
            {"NID": "fixture-seed"},
            navigation_start_ms=1_786_280_000_000.0,
        )

        self.assertEqual(bundle.sg_ss, "*fixture")
        self.assertEqual(
            bundle.navigation_url,
            "https://www.google.com/search?q=yatouv8&sei=fixture",
        )
        self.assertEqual(bundle.executed_script_count, 4)
        self.assertEqual(bundle.imported_cookie_count, 1)
        self.assertEqual(bundle.headers["referer"], response.url)
        self.assertIn("Chrome/150", bundle.headers["user-agent"])
        self.assertEqual(bundle.headers["sec-ch-ua-platform"], '"Windows"')
        self.assertEqual(
            {cookie["name"] for cookie in bundle.cookies},
            {"NID", "SG_SS"},
        )

    def test_bundle_applies_full_cookie_set(self) -> None:
        class Jar:
            def __init__(self) -> None:
                self.calls = []

            def set(self, name: str, value: str, **kwargs: object) -> None:
                self.calls.append((name, value, kwargs))

        bundle = yatouv8.ChallengeBundle(
            navigation_url="https://example.test/?sei=x",
            cookies=[
                {
                    "name": "NID",
                    "value": "seed",
                    "domain": ".google.com",
                    "path": "/",
                    "secure": True,
                },
                {
                    "name": "SG_SS",
                    "value": "*token",
                    "domain": "www.google.com",
                    "path": "/",
                    "secure": True,
                },
            ],
            headers={"referer": "https://www.google.com/"},
            sg_ss="*token",
            sg_ss_cookie={"name": "SG_SS", "value": "*token"},
            source_url="https://www.google.com/search?q=x",
            inline_script_count=4,
            executed_script_count=4,
            imported_cookie_count=1,
            drain={},
        )
        jar = Jar()

        self.assertEqual(bundle.apply_cookies(jar), 2)
        self.assertEqual([call[0] for call in jar.calls], ["NID", "SG_SS"])
        self.assertTrue(jar.calls[1][2]["secure"])
        self.assertEqual(
            bundle.request_kwargs(),
            {
                "url": "https://example.test/?sei=x",
                "headers": {"referer": "https://www.google.com/"},
            },
        )

    def test_solve_rejects_incomplete_or_failed_challenge(self) -> None:
        with self.assertRaisesRegex(yatouv8.ChallengeSolveError, "1 inline scripts"):
            yatouv8.solve_with_yatouv8(
                Response(challenge_html("void 0")),
                {},
                navigation_start_ms=1_786_280_000_000.0,
            )
        with self.assertRaisesRegex(yatouv8.ChallengeSolveError, r"script\[1\]"):
            yatouv8.solve_with_yatouv8(
                Response(
                    challenge_html(
                        "void 0",
                        "throw new TypeError('fixture')",
                        "void 0",
                        "void 0",
                    )
                ),
                {},
                navigation_start_ms=1_786_280_000_000.0,
            )

    def test_headers_follow_profile_language_and_platform(self) -> None:
        profile = yatouv8.BrowserProfile(
            user_agent="Mozilla/5.0 Chrome/151.0.0.0 Safari/537.36",
            platform="MacIntel",
            languages=["en-US", "en"],
        )

        headers = yatouv8.browser_headers(profile=profile)

        self.assertIn('"Chromium";v="151"', headers["sec-ch-ua"])
        self.assertEqual(headers["sec-ch-ua-platform"], '"macOS"')
        self.assertEqual(headers["accept-language"], "en-US,en;q=0.9")


if __name__ == "__main__":
    unittest.main()
