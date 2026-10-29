#!/usr/bin/env python3
"""Audit published sources, Git history and archives without printing private values.

Only tracked repository files, Git objects and explicitly supplied artifacts are
read. Host identifiers are collected in memory and never written to the report.
"""

import argparse
import getpass
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import unicodedata
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GENERIC = {"koorg", "user", "users", "root", "runner", "admin", "administrator",
           "build", "builder", "localhost", "rdappy", "public", "default"}


def normalized(value):
    return "".join(char for char in unicodedata.normalize("NFKD", value).casefold()
                   if char.isascii() and char.isalnum())


def host_identifiers(github_profile=False):
    values = [getpass.getuser(), Path.home().name, socket.gethostname()]
    values.extend(os.environ.get(key, "") for key in ("USERNAME", "COMPUTERNAME"))
    if github_profile:
        cli = shutil.which("gh")
        if not cli:
            raise RuntimeError("GitHub CLI is required for --github-profile.")
        result = subprocess.run([cli, "api", "user"], capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("The GitHub profile could not be read.")
        profile = json.loads(result.stdout)
        for key in ("name", "email"):
            value = profile.get(key) or ""
            if value and normalized(value) != "koorg" and "noreply.github.com" not in value:
                values.extend([value, *re.split(r"[\s._-]+", value.split("@", 1)[0])])
    return {normalized(value) for value in values
            if len(normalized(value)) >= 4 and normalized(value) not in GENERIC
            and "noreply" not in value and "github" not in value}


def privacy_categories(data, private_terms):
    """Return categories only, never a matching value or excerpt."""
    text = data.decode("utf-8", errors="replace")
    categories = set()
    compact = normalized(text)
    if any(term in compact for term in private_terms):
        categories.add("host/profile identifier")
    # Match account paths as data, while leaving generic examples and regexes alone.
    paths = re.findall(r"(?i)(?:[a-z]:[\\/]+Users[\\/]+|/mnt/[a-z]/Users/|/home/)([A-Za-z0-9_.-]+)[\\/]", text)
    if any(name.casefold() not in GENERIC for name in paths):
        categories.add("personal account path")
    if re.search(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b", text):
        categories.add("access token")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        categories.add("private key")
    return categories


def ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("Invalid ar signature.")
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[-2:] != b"`\n":
            raise ValueError("Invalid ar member header.")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58])
        offset += 60
        content = data[offset:offset + size]
        if len(content) != size:
            raise ValueError("Truncated ar member.")
        yield name, content
        offset += size + size % 2


class Auditor:
    def __init__(self, private_terms=()):
        self.private_terms = set(private_terms)
        self.findings = set()
        self.items = 0

    def inspect_text(self, label, data):
        self.items += 1
        for category in privacy_categories(data, self.private_terms):
            self.findings.add((label, category))

    def inspect(self, label, data):
        self.inspect_text(label + " [name]", label.encode("utf-8"))
        if data.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.inspect_text(label + " [comment]", archive.comment)
                for member in archive.infolist():
                    self.check_path(label, member.filename)
                    self.inspect_text(label + " [member metadata]", member.comment + member.extra)
                    if not member.is_dir():
                        self.inspect(label + "!" + member.filename, archive.read(member))
            return
        if data.startswith(b"!<arch>\n"):
            for name, content in ar_members(data):
                self.check_path(label, name)
                self.inspect(label + "!" + name, content)
            return
        if data.startswith(b"\x1f\x8b"):
            flags, offset = data[3], 10
            if flags & 4:
                size = int.from_bytes(data[offset:offset + 2], "little")
                self.inspect_text(label + " [gzip extra]", data[offset + 2:offset + 2 + size])
                offset += 2 + size
            for flag in (8, 16):
                if flags & flag:
                    end = data.index(b"\0", offset)
                    self.inspect_text(label + " [gzip metadata]", data[offset:end])
                    offset = end + 1
            self.inspect(label.removesuffix(".gz"), gzip.decompress(data))
            return
        if len(data) >= 512 and data[257:262] == b"ustar":
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
                for member in archive:
                    self.check_path(label, member.name)
                    if member.uid or member.gid or member.uname not in ("", "root") or member.gname not in ("", "root"):
                        self.findings.add((label, "non-neutral archive ownership"))
                    self.inspect_text(label + " [tar metadata]", json.dumps(member.pax_headers).encode())
                    if member.isfile():
                        self.inspect(label + "!" + member.name, archive.extractfile(member).read())
                    elif not member.isdir():
                        self.findings.add((label, "unexpected archive link or special file"))
            return
        self.inspect_text(label, data)

    def check_path(self, label, name):
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            self.findings.add((label, "unsafe archive path"))


def git(*args):
    process = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if process.returncode:
        raise RuntimeError("A repository inspection failed.")
    return process.stdout


def audit_repository(auditor, history=False):
    names = git("ls-files", "-z").decode("utf-8").split("\0")
    for name in filter(None, names):
        path = ROOT / name
        if path.is_file():
            auditor.inspect(name, path.read_bytes())
    # Include prepared new files before they have been added to the index.
    names = git("ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    for name in filter(None, names):
        auditor.inspect(name, (ROOT / name).read_bytes())
    if history:
        auditor.inspect_text("Git references", git("for-each-ref", "--format=%(refname) %(contents)"))
        auditor.inspect_text("Git commit metadata", git("log", "--all", "--format=%an <%ae>%n%cn <%ce>%n%B"))
        objects = git("rev-list", "--objects", "--all").decode("utf-8").splitlines()
        for entry in objects:
            identifier, _, name = entry.partition(" ")
            kind = git("cat-file", "-t", identifier).strip()
            if kind == b"blob":
                # Object IDs make historical reports independent of private filenames.
                auditor.inspect_text("Git object names", name.encode("utf-8"))
                auditor.inspect("Git blob " + identifier, git("cat-file", "blob", identifier))
            elif kind in (b"commit", b"tag"):
                auditor.inspect_text("Git metadata " + identifier, git("cat-file", kind.decode("ascii"), identifier))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path, help="explicit archive or file paths to inspect")
    parser.add_argument("--history", action="store_true", help="also inspect every reachable Git blob and commit")
    parser.add_argument("--github-profile", action="store_true", help="also check against the current account's name/email without printing them")
    args = parser.parse_args()
    try:
        auditor = Auditor(host_identifiers(args.github_profile))
        audit_repository(auditor, args.history)
        for path in args.artifacts:
            auditor.inspect(path.name, path.read_bytes())
        if auditor.findings:
            # Paths can themselves contain private identifiers; report categories only.
            counts = {}
            for _, category in auditor.findings:
                counts[category] = counts.get(category, 0) + 1
            print(json.dumps({"result": "failed", "categories": counts, "items": auditor.items}, sort_keys=True))
            return 1
        print(json.dumps({"result": "passed", "findings": 0, "items": auditor.items}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, tarfile.TarError, zipfile.BadZipFile):
        print("Audit could not be completed; no private data was written to this report.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
