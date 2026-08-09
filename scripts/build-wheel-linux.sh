#!/usr/bin/env bash

set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

# shellcheck source=prepare-manylinux.sh
source scripts/prepare-manylinux.sh

output_dir="${1:-dist}"
mkdir -p "${output_dir}"

interpreters=(
  /opt/python/cp310-cp310/bin/python
  /opt/python/cp311-cp311/bin/python
  /opt/python/cp312-cp312/bin/python
  /opt/python/cp313-cp313/bin/python
  /opt/python/cp314-cp314/bin/python
)

for interpreter in "${interpreters[@]}"; do
  [[ -x "${interpreter}" ]] || {
    echo "missing manylinux interpreter: ${interpreter}" >&2
    exit 2
  }
done

maturin_args=(
  build
  --release
  --locked
  --compatibility manylinux_2_28
  --out "${output_dir}"
)
maturin_args+=(--interpreter "${interpreters[@]}")
maturin "${maturin_args[@]}"

test_root="$(mktemp -d -t yatouv8-linux-wheel-test-XXXXXXXX)"
trap 'rm -rf "${test_root}"' EXIT

for index in "${!interpreters[@]}"; do
  minor="$((index + 10))"
  tag="cp3${minor}"
  wheel="$(find "${output_dir}" -maxdepth 1 -type f \
    -name "yatouv8-0.1.0-${tag}-${tag}-*manylinux_2_28_x86_64.whl" \
    -print -quit)"
  [[ -n "${wheel}" ]] || {
    echo "missing ${tag} manylinux_2_28_x86_64 wheel" >&2
    exit 2
  }
  python3 tools/build/verify_wheel.py \
    --wheel "${wheel}" \
    --expected-python "${tag}" \
    --expected-platform manylinux_2_28_x86_64

  site="${test_root}/${tag}"
  "${interpreters[$index]}" -m pip install \
    --disable-pip-version-check --no-input --no-deps --target "${site}" "${wheel}"
  PYTHONPATH="${site}" "${interpreters[$index]}" \
    -m unittest discover -s python/tests -v
done

sha256sum "${output_dir}"/*.whl
