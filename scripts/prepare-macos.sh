#!/usr/bin/env bash

# This file must be sourced so the V8 build environment survives into maturin.
set -Eeuo pipefail

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source scripts/prepare-macos.sh instead of executing it" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "prepare-macos.sh requires macOS" >&2
  return 2
fi

target_id="${YATOU_WHEEL_TARGET:-macos-arm64}"
matrix() {
  python3 tools/build/wheel_matrix.py field --target "${target_id}" --name "$1"
}

if [[ "$(matrix os)" != "macos" ]]; then
  echo "${target_id} is not a macOS target" >&2
  return 2
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install libclang 19+" >&2
  return 2
fi
if ! brew list --versions llvm@19 >/dev/null 2>&1; then
  brew install llvm@19
fi

llvm_prefix="$(brew --prefix llvm@19)"
clang_major="$("${llvm_prefix}/bin/clang" --version | sed -nE 's/.*clang version ([0-9]+).*/\1/p' | head -n 1)"
if [[ -z "${clang_major}" || "${clang_major}" -lt 19 ]]; then
  echo "V8 150 bindgen requires clang 19+, found: $("${llvm_prefix}/bin/clang" --version | head -n 1)" >&2
  return 2
fi
if [[ ! -e "${llvm_prefix}/lib/libclang.dylib" ]]; then
  echo "Homebrew LLVM did not provide ${llvm_prefix}/lib/libclang.dylib" >&2
  return 2
fi

xcrun --show-sdk-path >/dev/null
export YATOU_WHEEL_TARGET="${target_id}"
export V8_FROM_SOURCE=1
export PYTHON="${PYTHON:-$(command -v python3)}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export CARGO_TERM_COLOR=always
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
export NUM_JOBS="${NUM_JOBS:-$(sysctl -n hw.logicalcpu)}"
export LIBCLANG_PATH="${llvm_prefix}/lib"

# Keep CLANG_BASE_PATH unset: rusty_v8 uses its pinned Chromium clang for the
# V8 C++ build. Homebrew LLVM is only the bindgen libclang provider.
unset CLANG_BASE_PATH || true

python3 tools/build/prepare_v8_source.py \
  --cargo cargo \
  --output /tmp/yatouv8-v8-source-preparation.json

echo "YATOU_WHEEL_TARGET=${YATOU_WHEEL_TARGET}"
echo "V8_FROM_SOURCE=${V8_FROM_SOURCE}"
echo "LIBCLANG_PATH=${LIBCLANG_PATH}"
echo "MACOSX_DEPLOYMENT_TARGET=${MACOSX_DEPLOYMENT_TARGET}"
echo "NUM_JOBS=${NUM_JOBS}"
