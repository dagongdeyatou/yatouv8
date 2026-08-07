"""Build a content-addressed M9 corpus from archived and current public Google artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import urllib.request
from typing import Any


SCHEMA_VERSION = 1
LOADER_URLS = (
    "https://www.google.com/recaptcha/api.js?render=explicit",
    "https://www.recaptcha.net/recaptcha/api.js?render=explicit",
)
RELEASE_PATTERN = re.compile(
    r"https://www\.gstatic\.(?:com|cn)/recaptcha/releases/([^/]+)/recaptcha__([a-z-]+)\.js"
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: float) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS endpoints
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def store(root: pathlib.Path, data: bytes) -> pathlib.Path:
    sha = digest(data)
    relative = pathlib.Path("objects") / "sha256" / sha[:2] / sha
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(destination.read_bytes()) != sha:
            raise RuntimeError(f"content-address collision: {destination}")
    else:
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    return relative


def artifact(root: pathlib.Path, run: pathlib.Path, name: str, data: bytes, filename: str, url: str | None) -> dict[str, Any]:
    relative = store(root, data)
    (run / filename).write_bytes(data)
    return {
        "name": name,
        "filename": filename,
        "url": url,
        "sha256": digest(data),
        "size_bytes": len(data),
        "object_path": relative.as_posix(),
    }


def probe_source(loader: str) -> str:
    return f"""(() => {{
  const seed = document.createElement('script');
  document.head.appendChild(seed);
}})();
{loader}
(() => {{
  const scripts = Array.from(document.getElementsByTagName('script'));
  const inserted = scripts.find(script => typeof script.src === 'string' && script.src.includes('/recaptcha/releases/'));
  const cfg = globalThis.___grecaptcha_cfg || {{}};
  return {{
    api: globalThis.__recaptcha_api || null,
    client: globalThis.__google_recaptcha_client === true,
    render: Array.from(cfg.render || []),
    anchor_ms: Array.from(cfg['anchor-ms'] || []),
    execute_ms: Array.from(cfg['execute-ms'] || []),
    inserted: inserted ? {{
      src: inserted.src || null,
      type: inserted.type || '',
      async: inserted.async === true,
      charset: inserted.charset || '',
      cross_origin: inserted.crossOrigin || null,
      integrity: inserted.integrity || null
    }} : null
  }};
}})()
"""


def collect(arguments: argparse.Namespace) -> pathlib.Path:
    root = arguments.output_root.resolve()
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + secrets.token_hex(4)
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    releases: set[str] = set()
    second_stage_urls: dict[str, str] = {}

    for index, url in enumerate(LOADER_URLS):
        data, headers = fetch(url, arguments.timeout)
        text = data.decode("utf-8")
        match = RELEASE_PATTERN.search(text)
        if not match:
            raise RuntimeError(f"could not identify release URL in {url}")
        release, language = match.groups()
        release_url = match.group(0)
        releases.add(release)
        second_stage_urls[release_url] = language
        origin = "google" if "google.com" in url else "recaptcha-net"
        item = artifact(root, run, f"current-{origin}-api-loader", data, f"{origin}.api.js", url)
        probe = probe_source(text).encode()
        probe_item = artifact(root, run, f"current-{origin}-probe", probe, f"{origin}.probe.js", None)
        probe_item.update(
            {
                "class": "current_public_loader_probe",
                "release": release,
                "ordinal": index,
            }
        )
        item.update(
            {
                "class": "current_public_loader",
                "release": release,
                "language": language,
                "second_stage_url": release_url,
                "response_headers": headers,
                "probe_filename": probe_item["filename"],
                "probe_sha256": probe_item["sha256"],
                "ordinal": index,
            }
        )
        entries.extend((item, probe_item))

    if len(releases) != 1:
        raise RuntimeError(f"public mirrors disagree on release: {sorted(releases)}")

    for url, language in second_stage_urls.items():
        data, headers = fetch(url, arguments.timeout)
        item = artifact(root, run, "current-gstatic-second-stage", data, f"recaptcha__{language}.js", url)
        item.update(
            {
                "class": "current_public_second_stage",
                "release": next(iter(releases)),
                "language": language,
                "response_headers": headers,
            }
        )
        entries.append(item)

    reference = arguments.reference_root.resolve()
    archived = []
    for filename, expected in (
        ("model.js", "eb283e820750810020f120000c99008dcf8930d9ce9d8b881a01ff88157bb9ff"),
        ("enc", "f2f5fee92d9717e207fc88d4c9893370df86d23e78c47252fbf0f30422f086f0"),
    ):
        path = reference / filename
        if path.exists():
            data = path.read_bytes()
            if digest(data) != expected:
                raise RuntimeError(f"archived artifact hash changed: {path}")
            archived.append(artifact(root, run, f"archived-botguard-{filename}", data, f"archived-{filename}", None))
    entries.extend(archived)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "m9",
        "run_id": run_id,
        "captured_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "release": next(iter(releases)),
        "current_public_loader_claimed": True,
        "current_live_challenge_claimed": False,
        "mirror_release_match": True,
        "archived_artifacts_present": len(archived) == 2,
        "entries": entries,
    }
    manifest_bytes = canonical(manifest)
    manifest["manifest_sha256"] = digest(manifest_bytes)
    manifest_path = run / "corpus.manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    print(manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=pathlib.Path, default=pathlib.Path(".yatou/evidence/corpus/m9"))
    parser.add_argument(
        "--reference-root",
        type=pathlib.Path,
        default=pathlib.Path(".reference-cache/inside-recaptcha"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    collect(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
