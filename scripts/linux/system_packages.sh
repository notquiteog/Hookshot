#!/bin/sh
# The Linux AppImage's system packages on Ubuntu 22.04, as root: the one package list for every place it is built.
#  - .github/ci/appimage-build.Dockerfile, CI's build image (.github/workflows/appimage-build-image.yml makes it), whose
#    AppImage job then installs nothing;
#  - .github/workflows/linux-appimage.yml's "System packages" step, when that image is not there for these files (a pull
#    request that changes this list, before its image is made);
#  - scripts/linux/Dockerfile, the same build on any distribution (scripts/linux/docker.sh).
# A change here makes a new CI image (its tag is the hash of this file and that Dockerfile). Checked without a network
# by tests/test_appimage_package_retry.py, which runs this file with failing apt and PPA stand-ins.
# DEBIAN_FRONTEND=noninteractive is the caller's.
set -e

retry_packages() {
  for try in 1 2 3; do
    if "$@"; then return 0; else package_status=$?; fi
    if [ "$try" = 3 ]; then return "$package_status"; fi
    sleep 20
  done
}
base_packages() {
  apt-get update &&
    apt-get install -y --no-install-recommends software-properties-common gpg-agent
}
toolchain_packages() {
  # Enrollment can leave a source without its key after a network failure. Repair it before refreshing
  # indexes that depend on that key; retrying the base refresh first would stop at NO_PUBKEY (#2266).
  # --no-update only separates enrollment from the explicit, signed index refresh immediately afterward.
  # (libstdc++ 13, from the toolchain PPA: C++20 <format>; linked in statically)
  # Launchpad metadata connections can hang past the entire job's hour. Give each retry a real chance;
  # terminate enrollment after three minutes, then kill it if termination itself stalls.
  timeout --kill-after=5s 180s add-apt-repository -y --no-update ppa:ubuntu-toolchain-r/test &&
    apt-get update &&
    apt-get install -y --no-install-recommends g++-13 libstdc++-13-dev &&
    apt-get install -y --no-install-recommends git ca-certificates curl xz-utils zstd file unzip python3 \
    build-essential gcc-12 g++-12 libstdc++-12-dev nasm meson ninja-build cmake pkg-config \
    libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev libxinerama-dev \
    libxkbcommon-dev libwayland-dev wayland-protocols libdecor-0-dev libegl-dev libgles-dev libdrm-dev libgbm-dev \
    libpulse-dev libasound2-dev libpipewire-0.3-dev libudev-dev libdbus-1-dev libxft-dev libfontconfig1-dev zlib1g-dev
}
retry_packages base_packages
retry_packages toolchain_packages
