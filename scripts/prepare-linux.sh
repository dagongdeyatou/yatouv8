#!/usr/bin/env bash

# Source this file from a glibc x86_64 build container. V8's host-side tools
# stay native while Cargo/GN may emit glibc or musl code for x86_64/aarch64.
set -Eeuo pipefail

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source scripts/prepare-linux.sh instead of executing it" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "yatouv8 Linux builds require a glibc x86_64 build host" >&2
  return 2
fi

target_id="${YATOU_WHEEL_TARGET:-manylinux-x86_64}"
matrix() {
  python3 tools/build/wheel_matrix.py field --target "${target_id}" --name "$1"
}

target_os="$(matrix os)"
target_libc="$(matrix libc)"
rust_target="$(matrix rust_target)"
if [[ "${target_os}" != "linux" ]]; then
  echo "${target_id} is not a Linux wheel target" >&2
  return 2
fi

install_llvm19_apt() {
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg libglib2.0-dev pkg-config xz-utils

  # `apt-cache show` may succeed for metadata whose Candidate is `(none)`.
  # Always install the signed upstream LLVM repository before requesting the
  # versioned packages so old Ubuntu cross images cannot silently skip it.
  . /etc/os-release
  codename="${VERSION_CODENAME:-jammy}"
  keyring=/usr/share/keyrings/llvm-archive-keyring.gpg
  curl --fail --location --retry 3 --silent --show-error \
    https://apt.llvm.org/llvm-snapshot.gpg.key | gpg --dearmor > "${keyring}"
  echo "deb [signed-by=${keyring}] https://apt.llvm.org/${codename}/ llvm-toolchain-${codename}-19 main" \
    > /etc/apt/sources.list.d/llvm19.list
  apt-get update

  apt-get install -y --no-install-recommends clang-19 libclang-19-dev
  export PATH="/usr/lib/llvm-19/bin:${PATH}"
}

if command -v dnf >/dev/null 2>&1; then
  dnf -y install \
    clang clang-devel glib2-devel llvm-devel pkgconf-pkg-config xz
elif command -v apt-get >/dev/null 2>&1; then
  clang_major="$(clang --version 2>/dev/null | sed -nE 's/.*clang version ([0-9]+).*/\1/p' | head -n 1 || true)"
  if [[ -z "${clang_major}" || "${clang_major}" -lt 19 ]]; then
    install_llvm19_apt
  else
    apt-get update
    apt-get install -y --no-install-recommends libglib2.0-dev pkg-config xz-utils
  fi
else
  echo "unsupported Linux build image: dnf or apt-get is required" >&2
  return 2
fi

clang_major="$(clang --version | sed -nE 's/.*clang version ([0-9]+).*/\1/p' | head -n 1)"
if [[ -z "${clang_major}" || "${clang_major}" -lt 19 ]]; then
  echo "V8 150 bindgen requires clang 19+, found: $(clang --version | head -n 1)" >&2
  return 2
fi

clang_root="$(cd "$(dirname "$(command -v clang)")/.." && pwd)"
libclang="$({
  find "${clang_root}/lib" /usr/lib/llvm-19/lib /usr/lib64 /usr/lib \
    \( -type f -o -type l \) \
    \( -name 'libclang.so' -o -name 'libclang.so.*' \) 2>/dev/null || true
} | sort -V | tail -n 1)"
if [[ -z "${libclang}" ]]; then
  echo "clang 19+ installation did not provide libclang.so" >&2
  return 2
fi

export YATOU_WHEEL_TARGET="${target_id}"
export V8_FROM_SOURCE=1
export PYTHON="${PYTHON:-$(command -v python3)}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export CARGO_TERM_COLOR=always
export NUM_JOBS="${NUM_JOBS:-$(nproc)}"
export LIBCLANG_PATH="$(dirname "${libclang}")"

# Cargo's host-side bindgen inherits the Rust target but libclang does not
# automatically discover the cross image's glibc headers.  In particular,
# aarch64 bindgen otherwise combines /usr/include/features-time64.h with the
# x86_64 host search path and cannot resolve bits/wordsize.h.  Discover the
# target include directory from the installed cross compiler/sysroot and pass
# it only to the aarch64 GNU bindgen invocation.
if [[ "${rust_target}" == "aarch64-unknown-linux-gnu" ]]; then
  cross_cc=""
  for candidate in \
    "${CC_aarch64_unknown_linux_gnu:-}" \
    "${CC:-}" \
    aarch64-linux-gnu-gcc \
    aarch64-unknown-linux-gnu-gcc; do
    if [[ -n "${candidate}" ]] && command -v "${candidate}" >/dev/null 2>&1; then
      compiler_machine="$("${candidate}" -dumpmachine 2>/dev/null || true)"
      if [[ "${compiler_machine}" == aarch64* ]]; then
        cross_cc="${candidate}"
        break
      fi
    fi
  done
  if [[ -z "${cross_cc}" ]]; then
    echo "unable to locate the aarch64 GNU cross compiler for bindgen" >&2
    return 2
  fi

  target_sysroot="$("${cross_cc}" -print-sysroot 2>/dev/null || true)"
  target_multiarch="$("${cross_cc}" -print-multiarch 2>/dev/null || true)"
  target_include=""
  include_candidates=()
  if [[ -n "${target_sysroot}" ]]; then
    include_candidates+=(
      "${target_sysroot%/}/usr/include"
      "${target_sysroot%/}/include"
    )
  fi
  if [[ -n "${target_multiarch}" ]]; then
    include_candidates+=(
      "/usr/${target_multiarch}/include"
      "/usr/include/${target_multiarch}"
    )
  fi
  for candidate in "${include_candidates[@]}"; do
    if [[ -n "${candidate}" && -f "${candidate}/bits/wordsize.h" ]]; then
      target_include="${candidate}"
      break
    fi
  done
  if [[ -z "${target_include}" ]]; then
    while IFS= read -r wordsize_header; do
      case "${wordsize_header}" in
        *aarch64*|*arm64*)
          target_include="$(dirname "$(dirname "${wordsize_header}")")"
          break
          ;;
      esac
    done < <(find /usr /opt -type f -path '*/bits/wordsize.h' -print 2>/dev/null || true)
  fi
  if [[ -z "${target_include}" || ! -f "${target_include}/bits/wordsize.h" ]]; then
    echo "unable to locate aarch64 glibc headers for bindgen" >&2
    return 2
  fi

  bindgen_args="--target=${rust_target} -isystem ${target_include}"
  if [[ -n "${target_sysroot}" && "${target_sysroot}" != "/" && \
        -d "${target_sysroot}" ]]; then
    bindgen_args="${bindgen_args} --sysroot=${target_sysroot}"
  fi
  export BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_gnu="${bindgen_args}"
  echo "AARCH64_BINDGEN_CC=${cross_cc}"
  echo "AARCH64_BINDGEN_INCLUDE=${target_include}"
  echo "BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_gnu=${bindgen_args}"
fi

# Chromium's downloaded bindgen requires GLIBCXX_3.4.26, which the EL8
# manylinux_2_28 baseline intentionally does not provide. Build the exact
# Chromium bindgen version with the active host Rust toolchain instead. This
# keeps host-tool requirements separate from the wheel's target ABI.
host_tools="/tmp/yatouv8-host-tools"
host_rust_target="$(rustc -vV | sed -n 's/^host: //p')"
if [[ -z "${host_rust_target}" ]]; then
  echo "unable to determine the Rust host target" >&2
  return 2
fi
if [[ ! -x "${host_tools}/bin/bindgen" ]] || \
    [[ "$("${host_tools}/bin/bindgen" --version)" != "bindgen 0.72.1" ]]; then
  rm -rf "${host_tools}"
  cargo install bindgen-cli --version 0.72.1 --locked \
    --target "${host_rust_target}" --root "${host_tools}"
fi
export YATOU_BINDGEN_EXE="${host_tools}/bin/bindgen"
# Keep Chromium's own bundled rustfmt and libclang for Chromium GN actions.
# Their behavior and command-line flags are tied to that exact toolchain
# revision; LIBCLANG_PATH above remains available to Cargo build scripts
# outside Chromium's GN graph.

if [[ "${target_libc}" == "musl" ]]; then
  musl_sysroot="${RUSTY_V8_MUSL_SYSROOT:-${TARGET_HOME:-}}"
  if [[ -z "${musl_sysroot}" ]]; then
    compiler="${rust_target}-gcc"
    if command -v "${compiler}" >/dev/null 2>&1; then
      musl_sysroot="$("${compiler}" -print-sysroot)"
    fi
  fi
  if [[ -z "${musl_sysroot}" || ! -d "${musl_sysroot}/include" ]]; then
    echo "unable to locate the ${rust_target} musl sysroot" >&2
    return 2
  fi
  export RUSTY_V8_MUSL_SYSROOT="${musl_sysroot}"
else
  pkg-config --exists glib-2.0
  unset RUSTY_V8_MUSL_SYSROOT || true
fi

python3 tools/build/prepare_v8_source.py \
  --cargo cargo \
  --output /tmp/yatouv8-v8-source-preparation.json

echo "YATOU_WHEEL_TARGET=${YATOU_WHEEL_TARGET}"
echo "RUST_TARGET=${rust_target}"
echo "V8_FROM_SOURCE=${V8_FROM_SOURCE}"
echo "LIBCLANG_PATH=${LIBCLANG_PATH}"
echo "YATOU_BINDGEN_EXE=${YATOU_BINDGEN_EXE}"
echo "RUSTY_V8_MUSL_SYSROOT=${RUSTY_V8_MUSL_SYSROOT:-}"
echo "NUM_JOBS=${NUM_JOBS}"
