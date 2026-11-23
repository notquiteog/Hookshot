"""scripts/linux/Dockerfile is the Linux AppImage's CI build environment for any distribution: the same base system and the
same system packages as .github/workflows/linux-appimage.yml and CI's build image (.github/ci/appimage-build.Dockerfile).
All three install scripts/linux/system_packages.sh, the one package list. Reads the files; nothing is built.

Issue: the lists were kept by hand. A package added to the workflow alone (a new FFmpeg or SDL2 dependency) builds
in CI and fails in the container, or builds a different AppImage there; a newer base image puts a newer glibc in the
AppImage's sysroot, and the game it builds no longer runs on the systems the release is for.

    python -I -B tests/test_linux_docker_packages.py
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "scripts/linux/Dockerfile"
CI_DOCKERFILE = ROOT / ".github/ci/appimage-build.Dockerfile"
WORKFLOW = ROOT / ".github/workflows/linux-appimage.yml"
PACKAGES = ROOT / "scripts/linux/system_packages.sh"
BASE = "ubuntu:22.04"


def installs(text):
    """Every package an apt-get install names, with the commands' line continuations joined."""
    text = re.sub(r"\\\n", " ", text)
    packages = set()
    for args in re.findall(r"apt-get install([^&;\n]*)", text):
        packages.update(a for a in args.split() if not a.startswith("-"))
    return packages


def ppas(text):
    """Repository operands, not add-apt-repository's -y/--no-update flags."""
    text = re.sub(r"\\\n", " ", text)
    return set(re.findall(r"add-apt-repository\s+(?:-\S+\s+)*(\S+)", text))


class LinuxDockerPackages(unittest.TestCase):
    def setUp(self):
        self.docker = DOCKERFILE.read_text(encoding="utf-8")
        self.ci_docker = CI_DOCKERFILE.read_text(encoding="utf-8")
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.packages = PACKAGES.read_text(encoding="utf-8")

    def test_base_image(self):
        # (the workflow's container without the build image; the build image's own base)
        self.assertIn('echo "image=%s"' % BASE, self.workflow, "the workflow's container without the build image")
        for name, text in (("scripts/linux/Dockerfile", self.docker), ("the CI image", self.ci_docker)):
            with self.subTest(name):
                base = re.findall(r"^FROM\s+(\S+)", text, re.M)
                self.assertEqual(base, [BASE])

    def test_packages(self):
        self.assertIn("g++-13", installs(self.packages), "the package list was not found")
        self.assertIn("libx11-dev", installs(self.packages), "the package list was not found")
        # (no list of their own beside the shared one)
        for name, text in (("scripts/linux/Dockerfile", self.docker), ("the CI image", self.ci_docker),
                           ("the workflow", self.workflow)):
            with self.subTest(name):
                self.assertEqual(installs(text), set())
        for name, text in (("scripts/linux/Dockerfile", self.docker), ("the CI image", self.ci_docker)):
            with self.subTest(name):
                self.assertIn("COPY system_packages.sh /tmp/system_packages.sh\n", text)
                self.assertIn("sh -e /tmp/system_packages.sh", text)
        self.assertIn("sh -e .packages/scripts/linux/system_packages.sh", self.workflow)

    def test_ppa_options(self):
        ppa = "ppa:example/testing"
        for flags in ("", "-y ", "--no-update ", "-y --no-update ", "--no-update -y "):
            with self.subTest(flags=flags):
                self.assertEqual(ppas("timeout 180s add-apt-repository " + flags + ppa + " && apt-get update"), {ppa})
        self.assertEqual(ppas("add-apt-repository -y \\\n --no-update " + ppa), {ppa})
        self.assertEqual(ppas("apt-get update"), set())

    def test_ppas(self):
        self.assertEqual(ppas(self.packages), {"ppa:ubuntu-toolchain-r/test"}, "the list's PPA was not found")
        for text in (self.docker, self.ci_docker, self.workflow):
            self.assertEqual(ppas(text), set())


if __name__ == "__main__":
    unittest.main()
