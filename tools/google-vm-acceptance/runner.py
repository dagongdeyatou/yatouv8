"""Validate the observable terminal flow of an inline Google VM challenge."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import pathlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--script-limit", type=int, default=4)
    parser.add_argument("--no-execution-trace", action="store_true")
    return parser.parse_args()


def inline_scripts(html: str) -> list[str]:
    """Return inline script bodies in document order, matching the legacy probe."""

    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)


def outcome_kind(entry: dict[str, Any]) -> str | None:
    return entry.get("outcome", {}).get("value", {}).get("kind")


def trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    events = [event for event in trace.get("events", []) if event.get("level") == "l1"]
    operations = Counter(event.get("entry", {}).get("operation", "?") for event in events)
    void_observations = []
    undefined_gets = []
    for index, event in enumerate(events):
        entry = event.get("entry", {})
        if outcome_kind(entry) != "undefined":
            continue
        observation = {
            "index": index,
            "operation": entry.get("operation"),
            "target": entry.get("target"),
            "member": entry.get("member"),
        }
        if entry.get("operation") in {"call", "set"}:
            void_observations.append(observation)
        elif entry.get("operation") == "get":
            undefined_gets.append(observation)
    cookie_sets = [
        index
        for index, event in enumerate(events)
        if event.get("entry", {}).get("target") == "Document.prototype"
        and event.get("entry", {}).get("member") == "cookie"
        and event.get("entry", {}).get("operation") == "set"
    ]
    location_replaces = [
        index
        for index, event in enumerate(events)
        if event.get("entry", {}).get("target") == "Location.prototype"
        and event.get("entry", {}).get("member") == "replace"
        and event.get("entry", {}).get("operation") == "call"
    ]
    return {
        "l1_events": len(events),
        "operations": dict(operations),
        "void_observations": void_observations,
        "undefined_gets": undefined_gets,
        "cookie_set_indices": cookie_sets,
        "location_replace_indices": location_replaces,
    }


def source_gate_evidence(scripts: list[str]) -> dict[str, Any]:
    joined = "\n".join(scripts)

    def literal(name: str) -> str | None:
        match = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*(['\"])(.*?)\1", joined)
        return match.group(2) if match else None

    sp = literal("sp")
    ussv = literal("ussv")
    return {
        "sp_literal": sp,
        "ussv_literal": ussv,
        "sgs_gate_present": "window.sgs&&ussv&&sp" in joined,
        "sgs_gate_enabled_by_input": bool(sp and ussv),
        "fallback_present": "Z.then(function(a){a||la()}" in joined,
        "knitsail_initializer_present": "h.knitsail||(h.knitsail={})" in joined,
        "knitsail_lookup_present": "var c=C[g];if(c)" in joined,
    }


def valid_td(td_json: str | None) -> bool:
    if not td_json:
        return False
    try:
        value = json.loads(td_json)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(value, dict)
        and isinstance(value.get("ns"), (int, float))
        and isinstance(value.get("rs"), (int, float))
        and value["rs"] >= value["ns"]
    )


def valid_pending_navigation(
    navigation: dict[str, Any] | None,
    *,
    source_url: str,
) -> bool:
    """Validate the host-boundary redirect produced by the challenge."""

    if not (
        isinstance(navigation, dict)
        and navigation.get("kind") == "replace"
        and navigation.get("from") == source_url
        and isinstance(navigation.get("url"), str)
    ):
        return False
    source = urlsplit(source_url)
    destination = urlsplit(navigation["url"])
    source_query = dict(parse_qsl(source.query, keep_blank_values=True))
    destination_query = dict(parse_qsl(destination.query, keep_blank_values=True))
    return bool(
        (destination.scheme, destination.netloc, destination.path)
        == (source.scheme, source.netloc, source.path)
        and all(destination_query.get(key) == value for key, value in source_query.items())
        and destination_query.get("sei")
    )


def valid_sg_ss_handoff_cookie(cookie: dict[str, Any], *, source_url: str) -> bool:
    """Check that an exported SG_SS record is scoped to the challenge host."""

    hostname = (urlsplit(source_url).hostname or "").lower()
    domain = str(cookie.get("domain", "")).lstrip(".").lower()
    return bool(
        cookie.get("name") == "SG_SS"
        and str(cookie.get("value", "")).startswith("*")
        and domain == hostname
        and cookie.get("path") == "/"
    )


def redacted_cookie_record(cookie: dict[str, Any]) -> dict[str, Any]:
    """Retain cookie handoff metadata without persisting the challenge token."""

    value = str(cookie.get("value", ""))
    return {
        "name": cookie.get("name"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "secure": cookie.get("secure"),
        "httpOnly": cookie.get("httpOnly"),
        "sameSite": cookie.get("sameSite"),
        "expires": cookie.get("expires"),
        "value_prefix": value[:1],
        "value_length": len(value),
        "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def main() -> int:
    # Keep the pure acceptance helpers importable in contract-only jobs where
    # the native extension has not been built yet.
    import yatouv8

    arguments = parse_arguments()
    html = arguments.html.read_text(encoding="utf-8")
    scripts = inline_scripts(html)
    selected = scripts[: arguments.script_limit]
    execution_enabled = not arguments.no_execution_trace
    config = yatouv8.RuntimeConfig(
        url=arguments.url,
        viewport_width=1280,
        viewport_height=633,
        get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=200_000),
        execution_trace=yatouv8.ExecutionTraceConfig(
            enabled=execution_enabled,
            capture_source=True,
            max_scripts=512,
            max_source_bytes=4_194_304,
        ),
    )
    eval_errors = []
    execution_runs = []
    with yatouv8.Runtime(config) as runtime:
        for index, source in enumerate(selected):
            try:
                runtime.eval(source)
            except yatouv8.JSException as error:
                eval_errors.append({
                    "script_index": index,
                    "name": error.name,
                    "message": error.message,
                })
            if execution_enabled:
                execution_runs.append({
                    "script_index": index,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "capture": runtime.execution_trace,
                })
        # Keep these two probes before the trace snapshot for parity with the
        # historical 545-event command used to evaluate yatouv8.
        sgs_type = runtime.eval("typeof window.sgs")
        td_json = runtime.eval("JSON.stringify(window.td)")
        trace = runtime.trace
        knitsail_type = runtime.eval("typeof window.knitsail")
        cookie = runtime.eval("document.cookie") or ""
        exported_cookies = runtime.export_cookies()
        pending_navigation = runtime.pending_navigation

    summarized_trace = trace_summary(trace)
    gate = source_gate_evidence(selected)
    sg_ss_records = [cookie for cookie in exported_cookies if cookie.get("name") == "SG_SS"]
    predicates = {
        "scripts_return_without_exception": not eval_errors,
        "knitsail_initialized": knitsail_type == "object",
        "td_timing_valid": valid_td(td_json),
        "sg_ss_cookie_generated": cookie.startswith("SG_SS=*") and len(cookie) > 100,
        "cookie_set_observed": bool(summarized_trace["cookie_set_indices"]),
        "navigation_replace_observed": bool(summarized_trace["location_replace_indices"]),
        "structured_sg_ss_ready_for_session_handoff": bool(
            len(sg_ss_records) == 1
            and valid_sg_ss_handoff_cookie(sg_ss_records[0], source_url=arguments.url)
        ),
        "pending_navigation_ready_for_http_handoff": valid_pending_navigation(
            pending_navigation,
            source_url=arguments.url,
        ),
        # `sgs` is only selected when both page-provided gate inputs are
        # non-empty. It is intentionally not a universal terminal predicate.
        "sgs_gate_consistent_with_page_input": (
            sgs_type != "undefined" if gate["sgs_gate_enabled_by_input"] else sgs_type == "undefined"
        ),
    }
    accepted = all(predicates.values())
    artifact = {
        "schema": "yatouv8-google-vm-acceptance/v2",
        "input": {
            "path": str(arguments.html.resolve()),
            "sha256": hashlib.sha256(html.encode()).hexdigest(),
            "inline_script_count": len(scripts),
            "executed_script_count": len(selected),
            "url": arguments.url,
        },
        "accepted": accepted,
        "predicates": predicates,
        "terminal": {
            "sgs_type": sgs_type,
            "knitsail_type": knitsail_type,
            "td_json": td_json,
            "cookie_present": bool(cookie),
            "cookie_prefix": cookie[:8],
            "cookie_length": len(cookie),
            "cookie_sha256": hashlib.sha256(cookie.encode()).hexdigest(),
            "exported_sg_ss": (
                redacted_cookie_record(sg_ss_records[0]) if len(sg_ss_records) == 1 else None
            ),
            "pending_navigation": pending_navigation,
        },
        "source_gate_evidence": gate,
        "trace": summarized_trace,
        "eval_errors": eval_errors,
        "execution_runs": execution_runs,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(arguments.output)
    print(json.dumps({
        "accepted": accepted,
        "output": str(arguments.output.resolve()),
        "predicates": predicates,
        "terminal": artifact["terminal"],
        "trace": {
            "l1_events": summarized_trace["l1_events"],
            "operations": summarized_trace["operations"],
            "cookie_set_indices": summarized_trace["cookie_set_indices"],
            "location_replace_indices": summarized_trace["location_replace_indices"],
        },
        "pending_navigation": pending_navigation,
        "source_gate_evidence": gate,
    }, ensure_ascii=False, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
