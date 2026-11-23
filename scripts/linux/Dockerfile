# The Linux AppImage's build environment, for building it on any distribution: the system CI builds it in
# (.github/workflows/linux-appimage.yml, Ubuntu 22.04) with the same packages. Ubuntu 22.04 is not a preference: the
# AppImage carries this system's C library as the game's sysroot, so the game it builds runs on glibc 2.35 and newer.
# The packages are scripts/linux/system_packages.sh's, as CI's (.github/ci/appimage-build.Dockerfile).
#
# The image holds the system packages only. The checkout is mounted at /src when it runs, so build-linux/deps (LLVM,
# Python, FFmpeg, SDL2, headers) is kept between runs and the AppImage lands in the checkout's build-linux/.
# scripts/linux/docker.sh builds the image and runs it.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
# (scripts/linux/system_packages.sh: the one package list, which CI's build image and its AppImage job install too)
COPY system_packages.sh /tmp/system_packages.sh
RUN sh -e /tmp/system_packages.sh \
 && rm -rf /var/lib/apt/lists/* /tmp/system_packages.sh

# (run as the caller's user, whose home is not in the image: git and pip want a writable HOME)
ENV HOME=/tmp
# (the checkout belongs to the caller, not to the container's user under every runtime: git describe names the version)
RUN git config --system --add safe.directory /src
WORKDIR /src
CMD ["bash", "-c", "scripts/linux/deps.sh && scripts/linux/appimage.sh"]
