#!/usr/bin/env bash

set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

target_id="${1:-macos-arm64}"
output_dir="${2:-dist}"
export YATOU_WHEEL_TARGET="${target_id}"

matrix() {
  python3 tools/build/wheel_matrix.py field --target "${target_id}" --name "$1"
}

rust_target="$(matrix rust_target)"
platform_tag="$(matrix platform_tag)"
expected_arch="$(matrix arch)"
case "$(uname -m)" in
  x86_64) native_arch=x86_64 ;;
  arm64|aarch64) native_arch=aarch64 ;;
  *) native_arch="$(uname -m)" ;;
esac
if [[ "${native_arch}" != "${expected_arch}" ]]; then
  echo "${target_id} requires ${expected_arch}, current runner is ${native_arch}" >&2
  exit 2
fi

# shellcheck source=prepare-macos.sh
source scripts/prepare-macos.sh
rustup target add --toolchain 1.97.1 "${rust_target}"

versions=(3.10 3.11 3.12 3.13 3.14)
interpreters=()
for version in "${versions[@]}"; do
  interpreter="$(command -v "python${version}")"
  [[ -x "${interpreter}" ]] || {
    echo "missing macOS interpreter python${version}" >&2
    exit 2
  }
  interpreters+=("${interpreter}")
done

mkdir -p "${output_dir}"
python3.13 -m maturin build \
  --release \
  --locked \
  --auditwheel repair \
  --compatibility pypi \
  --target "${rust_target}" \
  --out "${output_dir}" \
  --interpreter "${interpreters[@]}"

python3 tools/build/wheel_matrix.py verify-dist \
  --target "${target_id}" \
  --dist "${output_dir}"

test_root="$(mktemp -d -t yatouv8-macos-wheel-test-XXXXXXXX)"
trap 'rm -rf "${test_root}"' EXIT
for index in "${!versions[@]}"; do
  version="${versions[$index]}"
  tag="cp${version//./}"
  wheel="$(find "${output_dir}" -maxdepth 1 -type f \
    -name "yatouv8-0.1.1-${tag}-${tag}-*${platform_tag}.whl" \
    -print -quit)"
  [[ -n "${wheel}" ]] || {
    echo "missing ${target_id} ${tag} wheel" >&2
    exit 2
  }
  site="${test_root}/${tag}"
  "${interpreters[$index]}" -m pip install \
    --disable-pip-version-check --no-input --no-index --no-deps \
    --target "${site}" "${wheel}"
  PYTHONPATH="${site}" "${interpreters[$index]}" \
    -m unittest discover -s python/tests -v
  PYTHONPATH="${site}" "${interpreters[$index]}" -c \
    "import yatouv8; assert yatouv8.v8_smoke_value() == '42'; r=yatouv8.Runtime(); assert r.eval('21 * 2') == 42; r.close()"
done

shasum -a 256 "${output_dir}"/*.whl
