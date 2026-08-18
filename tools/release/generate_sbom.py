"""Generate a deterministic CycloneDX 1.5 SBOM from locked Cargo metadata."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from typing import Any


def cargo_metadata(cargo: pathlib.Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(cargo), "metadata", "--locked", "--format-version", "1"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def generate(metadata: dict[str, Any]) -> dict[str, Any]:
    packages = sorted(metadata["packages"], key=lambda package: (package["name"], package["version"], package["id"]))
    components = []
    refs = {}
    for package in packages:
        reference = f"pkg:cargo/{package['name']}@{package['version']}"
        refs[package["id"]] = reference
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": reference,
            "name": package["name"],
            "version": package["version"],
            "purl": reference,
        }
        if package.get("license"):
            component["licenses"] = [{"expression": package["license"]}]
        if package.get("repository"):
            component["externalReferences"] = [
                {"type": "vcs", "url": package["repository"]}
            ]
        components.append(component)

    resolve = metadata["resolve"]
    dependencies = []
    if resolve is not None:
        for node in sorted(resolve["nodes"], key=lambda node: refs[node["id"]]):
            dependencies.append(
                {
                    "ref": refs[node["id"]],
                    "dependsOn": sorted(refs[dependency] for dependency in node["dependencies"]),
                }
            )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "tools": {"components": [{"type": "application", "name": "yatouv8-sbom-generator", "version": "1"}]},
            "component": {"type": "application", "name": "yatouv8", "version": "0.1.1"},
        },
        "components": components,
        "dependencies": dependencies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cargo", type=pathlib.Path, default=pathlib.Path.home() / ".cargo" / "bin" / "cargo.exe")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    document = generate(cargo_metadata(args.cargo))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
