#!/usr/bin/env bash

set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

target_id="${1:?usage: test-wheel-linux.sh TARGET_ID PYTHON_VERSION [DIST]}"
python_version="${2:?usage: test-wheel-linux.sh TARGET_ID PYTHON_VERSION [DIST]}"
dist="${3:-dist}"
control_python=/opt/python/cp310-cp310/bin/python
if [[ ! -x "${control_python}" ]]; then
  echo "native policy container is missing ${control_python}" >&2
  exit 2
fi

matrix() {
  "${control_python}" tools/build/wheel_matrix.py field --target "${target_id}" --name "$1"
}

expected_arch="$(matrix arch)"
platform_tag="$(matrix platform_tag)"
case "$(uname -m)" in
  x86_64) native_arch=x86_64 ;;
  aarch64|arm64) native_arch=aarch64 ;;
  *) native_arch="$(uname -m)" ;;
esac
if [[ "${native_arch}" != "${expected_arch}" ]]; then
  echo "${target_id} requires ${expected_arch}, current container is ${native_arch}" >&2
  exit 2
fi

tag="cp${python_version//./}"
python="/opt/python/${tag}-${tag}/bin/python"
if [[ ! -x "${python}" ]]; then
  echo "missing policy interpreter: ${python}" >&2
  exit 2
fi

"${control_python}" tools/build/wheel_matrix.py verify-dist \
  --target "${target_id}" \
  --dist "${dist}" \
  --python-version "${python_version}"

wheel="$(find "${dist}" -maxdepth 1 -type f \
  -name "yatouv8-0.1.0-${tag}-${tag}-*${platform_tag}.whl" \
  -print -quit)"
if [[ -z "${wheel}" ]]; then
  echo "missing ${target_id} ${tag} wheel" >&2
  exit 2
fi

test_root="$(mktemp -d -t yatouv8-linux-wheel-test-XXXXXXXX)"
trap 'rm -rf "${test_root}"' EXIT
site="${test_root}/site-packages"
"${python}" -m pip install \
  --disable-pip-version-check --no-input --no-index --no-deps \
  --target "${site}" "${wheel}"
PYTHONPATH="${site}" "${python}" -m unittest discover -s python/tests -v
PYTHONPATH="${site}" "${python}" -c \
  "import yatouv8; assert yatouv8.v8_smoke_value() == '42'; r=yatouv8.Runtime(); assert r.eval('21 * 2') == 42; r.close()"

echo "${target_id} ${python_version} native wheel test passed"
