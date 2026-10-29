"""Offline checks for distribution licensing, Debian metadata and privacy guards."""

import contextlib
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

import rdappy
from tools import build
from tools.audit_distribution import Auditor, ar_members, normalized, privacy_categories

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_embedded_licenses_retain_complete_upstream_texts(self):
        artistic = (ROOT / "LICENSE").read_text(encoding="utf-8").strip()
        bsd = (ROOT / "LICENSES/BSD-2-Clause.txt").read_text(encoding="utf-8").strip()
        self.assertIn(artistic, rdappy.ARTISTIC_LICENSE)
        self.assertEqual(bsd, rdappy.BSD_2_CLAUSE_LICENSE.strip())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(rdappy.main(["--license"]), 0)
        self.assertIn(artistic, output.getvalue())
        self.assertIn(bsd, output.getvalue())

    def test_versions_and_license_metadata_are_consistent(self):
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{rdappy.VERSION}"', metadata)
        self.assertIn('license = "Artistic-1.0-Perl AND BSD-2-Clause"', metadata)
        self.assertIn('authors = [{name = "koorg"}]', metadata)
        self.assertIn(f"ARG VERSION={rdappy.VERSION}", (ROOT / "Dockerfile").read_text())

    def test_debian_package_payload_metadata_and_checksums(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-deb-", dir=ROOT / "tests") as directory:
            package = build.build_deb(directory, build.DEFAULT_EPOCH)
            parts = dict(ar_members(package.read_bytes()))
            self.assertEqual(list(parts), ["debian-binary", "control.tar.gz", "data.tar.gz"])
            self.assertEqual(parts["debian-binary"], b"2.0\n")
            with tarfile.open(fileobj=io.BytesIO(parts["control.tar.gz"]), mode="r:gz") as archive:
                control = archive.extractfile("./control").read().decode()
                checksums = archive.extractfile("./md5sums").read().decode().splitlines()
            self.assertIn("Architecture: all\n", control)
            self.assertIn("Depends: python3 (>= 3.10)\n", control)
            self.assertIn("Maintainer: koorg <koorg@users.noreply.github.com>\n", control)
            self.assertIn(f"Version: {rdappy.VERSION}\n", control)
            with tarfile.open(fileobj=io.BytesIO(parts["data.tar.gz"]), mode="r:gz") as archive:
                executable = archive.extractfile("./usr/bin/rdappy").read()
                self.assertTrue(executable.startswith(b"#!/usr/bin/python3\n"))
                self.assertEqual(executable.split(b"\n", 1)[1], (ROOT / "rdappy.py").read_bytes().split(b"\n", 1)[1])
                self.assertEqual(archive.getmember("./usr/bin/rdappy").mode, 0o755)
                copyright_text = archive.extractfile("./usr/share/doc/rdappy/copyright").read().decode()
                self.assertIn("License: Artistic-1.0-Perl and BSD-2-Clause", copyright_text)
                self.assertIn("THIS SOFTWARE IS PROVIDED", copyright_text)
                for line in checksums:
                    digest, name = line.split("  ", 1)
                    self.assertEqual(digest, hashlib.md5(archive.extractfile("./" + name).read(), usedforsecurity=False).hexdigest())
                for member in archive:
                    self.assertEqual((member.uid, member.gid, member.uname, member.gname), (0, 0, "root", "root"))

    def test_debian_build_is_byte_reproducible_and_privacy_clean(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-deb-", dir=ROOT / "tests") as directory:
            first = build.build_deb(directory, build.DEFAULT_EPOCH).read_bytes()
            second = build.build_deb(directory, build.DEFAULT_EPOCH).read_bytes()
        self.assertEqual(first, second)
        auditor = Auditor({"syntheticprivateidentifier"})
        auditor.inspect("release.deb", first)
        self.assertEqual(auditor.findings, set())

    def test_privacy_guards_detect_identifiers_and_secrets_without_reporting_values(self):
        value = "SyntheticPrivateIdentifier"
        categories = privacy_categories((value + "_packager").encode(), {normalized(value)})
        self.assertEqual(categories, {"host/profile identifier"})
        token = "ghp_" + "x" * 36
        self.assertIn("access token", privacy_categories(token.encode(), set()))
        account = "C:" + "\\Users\\" + value + "\\source.py"
        self.assertIn("personal account path", privacy_categories(account.encode(), set()))

    def test_privacy_guards_allow_pseudonyms_and_reject_non_neutral_archive_owners(self):
        self.assertEqual(privacy_categories(b"koorg <koorg@users.noreply.github.com>", set()), set())
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo("file.txt")
            member.uname = "synthetic-builder"
            archive.addfile(member)
        auditor = Auditor()
        auditor.inspect("archive.tar", stream.getvalue())
        self.assertIn(("archive.tar", "non-neutral archive ownership"), auditor.findings)


if __name__ == "__main__":
    unittest.main()
