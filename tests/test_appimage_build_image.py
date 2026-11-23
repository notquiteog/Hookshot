"""CI's build image for the Linux AppImage: .github/ci/appimage-build.Dockerfile, made by
.github/workflows/appimage-build-image.yml, and used by .github/workflows/linux-appimage.yml when its tag exists.

Issue: the AppImage job fetched its compilers and libraries from archive.ubuntu.com and Launchpad's toolchain PPA on
every run, and on 2026-11-23 four runs failed or ran out their hour there. The image holds them; the job installs them
itself only when the image for its own files is missing. What this keeps: both workflows name the same tag (the same
hash of the same files, the same name), the job skips its install only on the image made for its checkout, a missing
image or a refused login picks ubuntu:22.04 instead of failing, and only main moves :latest. The "Find the image" and
"Build image" steps run here with a stand-in docker; nothing is built or fetched.

    python -I -B tests/test_appimage_build_image.py
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

# (the steps' scripts are bash on GitHub's runner and sh in the container)
RUN_ALL_SKIP = {"windows": "runs the workflow steps' shell scripts; checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = ROOT / ".github/workflows/linux-appimage.yml"
IMAGE = ROOT / ".github/workflows/appimage-build-image.yml"
RELEASE = ROOT / ".github/workflows/release.yml"
DOCKERFILE = ROOT / ".github/ci/appimage-build.Dockerfile"
# (the recipe: the Dockerfile, the package list and the image's workflow, so a changed one is never main's tag)
RECIPE = (".github/ci/appimage-build.Dockerfile", "scripts/linux/system_packages.sh",
          ".github/workflows/appimage-build-image.yml")
HASH = "${{ hashFiles(%s) }}" % ", ".join("'%s'" % path for path in RECIPE)
NAME = 'ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/hookshot-appimage-build'
FALLBACK = ("Package installs without fsync", "Package mirror", "Package list", "System packages")
INSTALL_IF = "if: steps.packages.outputs.installed != 'true'"


def job(text, name):
    """A job's block, up to the next job"""
    start = text.index("\n  %s:\n" % name)
    found = re.compile(r"\n  [A-Za-z0-9_-]+:\n").search(text, start + 1)
    return text[start:found.start() if found else len(text)]


def step(text, name):
    """(a step's block, its run: script with the step's indentation taken off)"""
    start = text.index("      - name: %s\n" % name)
    end = text.find("\n      - ", start + 1)
    block = text[start:end if end >= 0 else len(text)]
    if "        run: |\n" not in block:
        return block, None
    lines = []
    for line in block[block.index("        run: |\n") + len("        run: |\n"):].splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:])
    return block, "\n".join(lines) + "\n"


class Wiring(unittest.TestCase):
    def setUp(self):
        self.appimage = APPIMAGE.read_text(encoding="utf-8")
        self.image = IMAGE.read_text(encoding="utf-8")
        self.docker = DOCKERFILE.read_text(encoding="utf-8")

    def test_one_tag_for_both_workflows(self):
        find, find_run = step(job(self.appimage, "image"), "Find the image")
        build, build_run = step(self.image, "Build and push")
        for block, run in ((find, find_run), (build, build_run)):
            self.assertIn("HASH: " + HASH + "\n", block)
            self.assertIn(NAME, run)
            self.assertIn("test -n \"$HASH\"", run)
        self.assertIn('image="%s:$HASH"' % NAME, find_run)
        self.assertIn('-t "$name:$HASH" scripts/linux', build_run)
        self.assertIn('--build-arg "HOOKSHOT_CI_IMAGE=$HASH"', build_run)
        self.assertIn("-f .github/ci/appimage-build.Dockerfile", build_run)
        # (the image's GitHub page and its commit)
        self.assertIn("org.opencontainers.image.source=$GITHUB_SERVER_URL/$GITHUB_REPOSITORY", build_run)

    def test_image_workflow_triggers_and_rights(self):
        triggers = self.image[:self.image.index("\npermissions:")]
        for event in ("push", "pull_request"):
            with self.subTest(event):
                # (the event's own lines, indented under it)
                block = re.search(r"\n  %s:\n((?:    .*\n)+)" % event, triggers + "\n").group(1)
                self.assertEqual(re.findall(r"^      - (\S+)$", block, re.M), list(RECIPE))
        self.assertIn("  push:\n    branches: [main]\n", triggers)
        self.assertIn("\n  workflow_dispatch:", triggers)
        self.assertNotIn("pull_request_target", self.image)
        # (a pull request from a fork has a token that may not push here: its job does not run, and its build installs)
        self.assertIn("    if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == "
                      "github.repository\n", self.image)
        self.assertIn("\npermissions:\n  contents: read\n", self.image)
        self.assertIn("    permissions:\n      contents: read\n      packages: write\n", self.image)
        self.assertEqual(self.image.count("packages: write"), 1)
        self.assertNotIn("packages: write", self.appimage)
        # (:latest only from main; a run by hand on a branch pushes its own hash tag)
        build, run = step(self.image, "Build and push")
        self.assertIn("LATEST: ${{ github.ref == 'refs/heads/main' }}", build)
        self.assertIn('if [ "$LATEST" = true ]; then\n  docker tag "$name:$HASH" "$name:latest"', run)
        self.assertLess(run.index('docker run --rm "$name:$HASH"'), run.index('docker push "$name:$HASH"'))

    def test_marker_is_the_hash(self):
        self.assertIn("ARG HOOKSHOT_CI_IMAGE\n", self.docker)
        self.assertIn('test -n "$HOOKSHOT_CI_IMAGE"', self.docker)
        self.assertTrue(self.docker.rstrip().endswith('&& echo "$HOOKSHOT_CI_IMAGE" > /etc/hookshot-ci-image'))
        # (nothing of the image's own making left behind for the AppImage job: dpkg's fsync again, no package lists)
        self.assertIn("rm -rf /var/lib/apt/lists/* /tmp/system_packages.sh /etc/dpkg/dpkg.cfg.d/force-unsafe-io", self.docker)

    def test_same_mirror_in_the_image_and_the_fallback(self):
        _, mirror = step(job(self.appimage, "appimage"), "Package mirror")
        for line in mirror.strip().splitlines():
            self.assertIn(line, self.docker)

    def test_appimage_job_runs_in_the_found_image(self):
        image, appimage = job(self.appimage, "image"), job(self.appimage, "appimage")
        self.assertIn("    needs: image\n", appimage)
        self.assertIn("    container:\n      image: ${{ needs.image.outputs.image }}\n", appimage)
        # (a login only for the build image: Docker Hub refuses a GitHub token, and empty credentials are none)
        self.assertIn("        username: ${{ needs.image.outputs.prebuilt == 'true' && github.actor || '' }}\n", appimage)
        self.assertIn("        password: ${{ needs.image.outputs.prebuilt == 'true' && secrets.GITHUB_TOKEN || '' }}\n",
                      appimage)
        for rights in (image, appimage):
            self.assertIn("      packages: read\n", rights)
        # (the same runs: a skipped image job would skip the build)
        when = re.compile(r"\n    if: >-\n(.*?)\n    [a-z-]+:", re.S)
        self.assertEqual(when.search(image).group(1), when.search(appimage).group(1))
        for output in ("image", "hash", "prebuilt"):
            self.assertIn("      %s: ${{ steps.find.outputs.%s }}\n" % (output, output), image)
        # (the image job hashes the checkout the build makes)
        checkout = image[image.index("      - uses: actions/checkout@"):image.index("      - name: Find the image")]
        self.assertIn("ref: ${{ inputs.tag }}", checkout)
        for path in RECIPE:
            self.assertIn("            %s\n" % path, checkout)

    def test_install_only_without_the_image(self):
        appimage = job(self.appimage, "appimage")
        names = re.findall(r"\n      - (?:name: (.+)|uses: )", appimage)
        self.assertEqual(names[:5], ["Build image"] + list(FALLBACK), "the install's steps follow the image check")
        for name in FALLBACK:
            with self.subTest(name):
                self.assertIn(INSTALL_IF, step(appimage, name)[0])
        self.assertNotIn("if:", step(appimage, "Build image")[0])
        # (the repository's checkout comes after the install: it needs git)
        self.assertLess(appimage.index("      - name: System packages"),
                        appimage.index("fetch-depth: 0"))

    def test_release_lets_the_build_read_the_image(self):
        release = RELEASE.read_text(encoding="utf-8")
        linux = job(release, "linux")
        self.assertIn("uses: ./.github/workflows/linux-appimage.yml", linux)
        self.assertIn("      packages: read\n", linux)


def stub(folder, name, body):
    path = folder / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


@unittest.skipIf(os.name == "nt", "the steps' shell scripts")
class Steps(unittest.TestCase):
    def find(self, login=0, manifest=0):
        """The "Find the image" step with a stand-in docker: (its outputs, what docker was asked)"""
        _, script = step(job(APPIMAGE.read_text(encoding="utf-8"), "image"), "Find the image")
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory(prefix="appimage-image-") as temp:
            folder = Path(temp)
            tools = folder / "bin"
            tools.mkdir()
            log = folder / "docker.log"
            stub(tools, "docker", 'echo "$*" >> "%s"\ncase "$1" in login) cat >/dev/null; exit %d;; manifest) exit %d;; esac\n'
                 'exit 99\n' % (log, login, manifest))
            out = folder / "output"
            out.write_text("", encoding="utf-8")
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"], GITHUB_OUTPUT=str(out),
                       HASH="ab" * 32, GH_TOKEN="token", GITHUB_ACTOR="someone", GITHUB_REPOSITORY_OWNER="NotQuiteOG")
            # (GitHub's bash: --noprofile --norc -eo pipefail)
            result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
            return outputs, log.read_text(encoding="utf-8").splitlines()

    def test_existing_image(self):
        outputs, calls = self.find()
        tag = "ghcr.io/notquiteog/hookshot-appimage-build:" + "ab" * 32
        self.assertEqual(outputs, {"hash": "ab" * 32, "image": tag, "prebuilt": "true"})
        self.assertEqual(calls, ["login ghcr.io -u someone --password-stdin", "manifest inspect " + tag])

    def test_missing_image_is_plain_ubuntu(self):
        outputs, _ = self.find(manifest=1)
        self.assertEqual(outputs, {"hash": "ab" * 32, "image": "ubuntu:22.04", "prebuilt": "false"})

    def test_refused_login_still_looks_for_a_public_image(self):
        outputs, calls = self.find(login=1)
        self.assertEqual(outputs["prebuilt"], "true")
        self.assertEqual(len(calls), 2)
        outputs, _ = self.find(login=1, manifest=1)
        self.assertEqual(outputs["image"], "ubuntu:22.04")

    def check(self, marker, hash_="cd" * 32):
        """The AppImage job's "Build image" step with the marker at a temporary path: its outputs"""
        _, script = step(job(APPIMAGE.read_text(encoding="utf-8"), "appimage"), "Build image")
        self.assertEqual(script.count("/etc/hookshot-ci-image"), 1)
        with tempfile.TemporaryDirectory(prefix="appimage-marker-") as temp:
            folder = Path(temp)
            path = folder / "hookshot-ci-image"
            if marker is not None:
                path.write_text(marker + "\n", encoding="utf-8")
            out = folder / "output"
            out.write_text("", encoding="utf-8")
            env = dict(os.environ, GITHUB_OUTPUT=str(out), HASH=hash_, IMAGE="some-image")
            result = subprocess.run([shutil.which("sh"), "-e", "-c", script.replace("/etc/hookshot-ci-image", str(path))],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return out.read_text(encoding="utf-8")

    def test_install_skipped_only_for_this_checkouts_image(self):
        self.assertEqual(self.check("cd" * 32), "installed=true\n")
        self.assertEqual(self.check("ef" * 32), "")
        self.assertEqual(self.check(None), "")
        # (no hash from the image job: never taken for a match, even with an empty marker)
        self.assertEqual(self.check("", hash_=""), "")


if __name__ == "__main__":
    unittest.main()
