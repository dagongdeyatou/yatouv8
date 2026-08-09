#!/usr/bin/env bash

set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

target_id="${1:-manylinux-x86_64}"
output_dir="${2:-dist}"
export YATOU_WHEEL_TARGET="${target_id}"

matrix() {
  python3 tools/build/wheel_matrix.py field --target "${target_id}" --name "$1"
}

rust_target="$(matrix rust_target)"
platform_tag="$(matrix platform_tag)"
compatibility="$(matrix compatibility)"
build_mode="$(matrix build_mode)"

# shellcheck source=prepare-linux.sh
source scripts/prepare-linux.sh

mkdir -p "${output_dir}"

versions=(3.10 3.11 3.12 3.13 3.14)
if [[ "${build_mode}" == "native-container" ]]; then
  interpreters=()
  for version in "${versions[@]}"; do
    tag="cp${version//./}"
    interpreters+=("/opt/python/${tag}-${tag}/bin/python")
  done
else
  # Maturin 1.14 resolves these symbolic names from its bundled target
  # sysconfig without attempting to execute a target-architecture Python.
  interpreters=(python3.10 python3.11 python3.12 python3.13 python3.14)
fi

if [[ "${build_mode}" == "native-container" ]]; then
  for interpreter in "${interpreters[@]}"; do
    [[ -x "${interpreter}" ]] || {
      echo "missing native policy interpreter: ${interpreter}" >&2
      exit 2
    }
  done
fi

maturin_args=(
  build
  --release
  --locked
  --auditwheel repair
  --compatibility "${compatibility}"
  --target "${rust_target}"
  --out "${output_dir}"
)
maturin_args+=(--interpreter "${interpreters[@]}")
maturin "${maturin_args[@]}"

python3 tools/build/wheel_matrix.py verify-dist \
  --target "${target_id}" \
  --dist "${output_dir}"

if [[ "${build_mode}" == "native-container" ]]; then
  for version in "${versions[@]}"; do
    bash scripts/test-wheel-linux.sh "${target_id}" "${version}" "${output_dir}"
  done
else
  echo "${target_id}: runtime tests are deferred to its native ${platform_tag} container"
fi

sha256sum "${output_dir}"/*.whl
