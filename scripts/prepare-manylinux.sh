#!/usr/bin/env bash

# Backward-compatible entry point for the original x86_64 manylinux stage.
export YATOU_WHEEL_TARGET="${YATOU_WHEEL_TARGET:-manylinux-x86_64}"
# shellcheck source=prepare-linux.sh
source "$(dirname "${BASH_SOURCE[0]}")/prepare-linux.sh"
