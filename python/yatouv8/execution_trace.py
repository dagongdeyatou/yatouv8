"""Post-process V8 precise coverage into symbol-oriented blocker candidates."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _utf16_offset(source: str, character_offset: int) -> int:
    return len(source[:character_offset].encode("utf-16-le")) // 2


def analyze_execution_trace(
    capture: Mapping[str, Any],
    symbols: Iterable[str] = ("knitsail", "td", "sgs"),
    *,
    max_candidates: int = 100,
) -> dict[str, Any]:
    """Map watched symbols to hit/missed V8 ranges and rank blocker candidates.

    Inspector range offsets are UTF-16 code-unit offsets. This helper preserves
    that coordinate system so findings point back to the exact captured source.
    A symbol inside a zero-count range is direct evidence that its containing
    initialization block was parsed but not executed.
    """

    if not isinstance(capture, Mapping):
        raise TypeError("capture must be a mapping")
    watched = tuple(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
    occurrences: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, int, int, str]] = set()

    for script in capture.get("scripts", []):
        if not isinstance(script, Mapping):
            continue
        source = script.get("source")
        if not isinstance(source, str):
            continue
        script_id = str(script.get("script_id", ""))
        role = str(script.get("role", "unknown"))
        ranges: list[dict[str, Any]] = []
        for function in script.get("functions", []):
            if not isinstance(function, Mapping):
                continue
            function_name = str(function.get("functionName", ""))
            for item in function.get("ranges", []):
                if not isinstance(item, Mapping):
                    continue
                ranges.append({
                    "function_name": function_name,
                    "start_offset": int(item.get("startOffset", 0)),
                    "end_offset": int(item.get("endOffset", 0)),
                    "count": int(item.get("count", 0)),
                })

        snippet_by_range = {
            (int(item.get("start_offset", 0)), int(item.get("end_offset", 0))): item
            for item in script.get("missed_range_snippets", [])
            if isinstance(item, Mapping)
        }
        for symbol in watched:
            cursor = 0
            while True:
                character_offset = source.find(symbol, cursor)
                if character_offset < 0:
                    break
                offset = _utf16_offset(source, character_offset)
                covering = [
                    item
                    for item in ranges
                    if item["start_offset"] <= offset < item["end_offset"]
                ]
                covering.sort(key=lambda item: item["end_offset"] - item["start_offset"])
                most_specific = covering[0] if covering else None
                occurrence = {
                    "symbol": symbol,
                    "script_id": script_id,
                    "role": role,
                    "offset": offset,
                    "status": (
                        "missed"
                        if most_specific and most_specific["count"] == 0
                        else "hit" if most_specific else "unmapped"
                    ),
                    "most_specific_range": most_specific,
                    "covering_ranges": covering,
                }
                occurrences.append(occurrence)
                for item in covering:
                    if item["count"] != 0:
                        continue
                    key = (
                        script_id,
                        item["start_offset"],
                        item["end_offset"],
                        symbol,
                    )
                    if key in seen_candidates:
                        continue
                    seen_candidates.add(key)
                    snippet = snippet_by_range.get(
                        (item["start_offset"], item["end_offset"]), {}
                    )
                    candidates.append({
                        "rank_class": 0,
                        "reason": "watched_symbol_inside_zero_count_range",
                        "symbol": symbol,
                        "script_id": script_id,
                        "role": role,
                        **item,
                        "context": snippet.get("context"),
                        "context_start_offset": snippet.get("context_start_offset"),
                        "context_end_offset": snippet.get("context_end_offset"),
                    })
                cursor = character_offset + max(1, len(symbol))

        if role == "yatouv8_eval_wrapper":
            continue
        for item in script.get("missed_range_snippets", []):
            if not isinstance(item, Mapping):
                continue
            start = int(item.get("start_offset", 0))
            end = int(item.get("end_offset", start))
            key = (script_id, start, end, "")
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            candidates.append({
                "rank_class": 1,
                "reason": "zero_count_range_in_target_script",
                "symbol": None,
                "script_id": script_id,
                "role": role,
                "function_name": str(item.get("function_name", "")),
                "start_offset": start,
                "end_offset": end,
                "count": 0,
                "context": item.get("context"),
                "context_start_offset": item.get("context_start_offset"),
                "context_end_offset": item.get("context_end_offset"),
            })

    candidates.sort(
        key=lambda item: (
            int(item["rank_class"]),
            0 if item.get("role") == "nested_dynamic_script" else 1,
            int(item["start_offset"]),
        )
    )
    return {
        "schema_version": 1,
        "watched_symbols": list(watched),
        "symbol_occurrences": occurrences,
        "ranked_blockers": candidates[:max_candidates],
        "summary": {
            "symbol_occurrences": len(occurrences),
            "missed_symbol_occurrences": sum(
                item["status"] == "missed" for item in occurrences
            ),
            "ranked_blockers": min(len(candidates), max_candidates),
        },
    }
