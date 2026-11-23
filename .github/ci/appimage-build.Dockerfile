# CI's build image for the Linux AppImage (.github/workflows/linux-appimage.yml): Ubuntu 22.04 with the system packages
# already installed, so a run no longer fetches them from archive.ubuntu.com and Launchpad's toolchain PPA (on
# 2026-11-23 both were slow or answering 503, and four runs failed or ran out their hour in that step).
# .github/workflows/appimage-build-image.yml builds it, with scripts/linux as its context, and pushes it to this
# repository owner's GHCR as hookshot-appimage-build:<hash>, the hash being hashFiles() of this file and
# scripts/linux/system_packages.sh. The AppImage job runs in that tag when it exists, and installs the packages itself
# when it does not, as before.
#
# The same packages and the same base as the job's own install: scripts/linux/system_packages.sh is the one list. Ubuntu
# 22.04 is not a preference: the AppImage carries this system's C library as the game's sysroot (glibc 2.35).
FROM ubuntu:22.04

# (the hash this image is made for, which the AppImage job compares with its own files' before it skips its install)
ARG HOOKSHOT_CI_IMAGE
ARG DEBIAN_FRONTEND=noninteractive
COPY system_packages.sh /tmp/system_packages.sh
# (the mirror and apt's retries are the AppImage job's "Package mirror" step's, kept in the image: its runs are in Azure
# too. dpkg without an fsync per file only while the image is made)
RUN test -n "$HOOKSHOT_CI_IMAGE" \
 && echo force-unsafe-io > /etc/dpkg/dpkg.cfg.d/force-unsafe-io \
 && sed -i -E 's#http://(archive|security)\.ubuntu\.com/ubuntu#http://azure.archive.ubuntu.com/ubuntu#g' /etc/apt/sources.list \
 && printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\n' > /etc/apt/apt.conf.d/80-ci-network \
 && sh -e /tmp/system_packages.sh \
 && rm -rf /var/lib/apt/lists/* /tmp/system_packages.sh /etc/dpkg/dpkg.cfg.d/force-unsafe-io \
 && echo "$HOOKSHOT_CI_IMAGE" > /etc/hookshot-ci-image
