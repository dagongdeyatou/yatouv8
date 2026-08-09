#!/usr/bin/env bash

# This file must be sourced so the V8 build environment survives into maturin.
set -Eeuo pipefail

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source scripts/prepare-manylinux.sh instead of executing it" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "the current build stage requires Linux x86_64" >&2
  return 2
fi

if ! command -v dnf >/dev/null 2>&1; then
  echo "dnf is required; run this script inside manylinux_2_28_x86_64" >&2
  return 2
fi

dnf -y install \
  clang \
  clang-devel \
  glib2-devel \
  llvm-devel \
  pkgconf-pkg-config

clang_major="$(clang --version | sed -nE 's/.*clang version ([0-9]+).*/\1/p' | head -n 1)"
if [[ -z "${clang_major}" || "${clang_major}" -lt 19 ]]; then
  echo "V8 150 bindgen requires clang 19+, found: $(clang --version | head -n 1)" >&2
  return 2
fi

libclang="$({
  find /usr/lib64 /usr/lib /opt \
    \( -type f -o -type l \) \
    \( -name 'libclang.so' -o -name 'libclang.so.*' \) 2>/dev/null || true
} | sort -V | tail -n 1)"
if [[ -z "${libclang}" ]]; then
  echo "clang-devel did not provide libclang.so" >&2
  return 2
fi

export V8_FROM_SOURCE=1
export PYTHON="${PYTHON:-$(command -v python3)}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export CARGO_TERM_COLOR=always
export NUM_JOBS="${NUM_JOBS:-$(nproc)}"
export LIBCLANG_PATH="$(dirname "${libclang}")"

pkg-config --exists glib-2.0
python3 tools/build/prepare_v8_source.py \
  --cargo cargo \
  --output /tmp/yatouv8-v8-source-preparation.json

echo "V8_FROM_SOURCE=${V8_FROM_SOURCE}"
echo "LIBCLANG_PATH=${LIBCLANG_PATH}"
echo "NUM_JOBS=${NUM_JOBS}"
