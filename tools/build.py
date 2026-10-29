#!/usr/bin/env python3
"""Build reproducible Python and Debian distributions without downloading tools."""

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import zipfile
from email.utils import format_datetime

BACKEND_VERSION = "82.0.1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPOCH = int(datetime(2026, 10, 29, tzinfo=timezone.utc).timestamp())


def application_version():
    tree = ast.parse((ROOT / "rdappy.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("The application version is missing.")


def normalize_wheel(path, epoch):
    timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    temporary = path.with_suffix(".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(contents, key=lambda name: (".dist-info/" in name, name)):
                info = zipfile.ZipInfo(name, timestamp)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, contents[name], compresslevel=9)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_sdist(path, epoch):
    entries = []
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("The source archive contains a non-regular file.")
            stream = archive.extractfile(member) if member.isfile() else None
            entries.append((member.name, stream.read() if stream else None))
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("wb") as output:
            with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=epoch, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for name, data in sorted(entries):
                        info = tarfile.TarInfo(name)
                        info.mtime = epoch
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        if data is None:
                            info.type = tarfile.DIRTYPE
                            info.mode = 0o755
                            archive.addfile(info)
                        else:
                            info.mode = 0o644
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def gzip_bytes(data, epoch):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=epoch, compresslevel=9) as stream:
        stream.write(data)
    return output.getvalue()


def deb_tar(files, epoch):
    """Create a Debian-compatible USTAR archive with neutral ownership."""
    output = io.BytesIO()
    directories = set()
    for name in files:
        parent = Path(name).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories, key=lambda name: (name.count("/"), name)):
            info = tarfile.TarInfo("./" + name)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            archive.addfile(info)
        for name, (data, mode) in sorted(files.items()):
            info = tarfile.TarInfo("./" + name)
            info.size, info.mode, info.mtime = len(data), mode, epoch
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    return gzip_bytes(output.getvalue(), epoch)


def deb_copyright():
    def stanza(name, value):
        return "License: " + name + "\n" + "\n".join(" " + line if line else " ." for line in value.strip().splitlines()) + "\n"
    header = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: rdappy
Upstream-Contact: https://github.com/koorg
Source: https://github.com/koorg/rdappy

Files: *
Copyright: 2026 koorg
           2012-2023 CentralNic Ltd.
           2023-2026 Gavin Brown.
License: Artistic-1.0-Perl and BSD-2-Clause
Comment: Python port of App::rdapper with adaptations based on Net::RDAP.
 Original credits and licensing details are also provided in NOTICE.

"""
    return (header + stanza("Artistic-1.0-Perl", (ROOT / "LICENSE").read_text(encoding="utf-8")) + "\n"
            + stanza("BSD-2-Clause", (ROOT / "LICENSES/BSD-2-Clause.txt").read_text(encoding="utf-8"))).encode("utf-8")


def build_deb(output, epoch):
    """Build an architecture-independent .deb using only the standard library."""
    release = application_version()
    source = (ROOT / "rdappy.py").read_bytes()
    application = b"#!/usr/bin/python3\n" + source.split(b"\n", 1)[1]
    timestamp = format_datetime(datetime.fromtimestamp(epoch, tz=timezone.utc))
    changelog = (f"rdappy ({release}) stable; urgency=medium\n\n"
                 "  * Édition française du client RDAP avec les licences complètes.\n\n"
                 f" -- koorg <koorg@users.noreply.github.com>  {timestamp}\n").encode("utf-8")
    data = {
        "usr/bin/rdappy": (application, 0o755),
        "usr/share/doc/rdappy/copyright": (deb_copyright(), 0o644),
        "usr/share/doc/rdappy/NOTICE": ((ROOT / "NOTICE").read_bytes(), 0o644),
        "usr/share/doc/rdappy/changelog.gz": (gzip_bytes(changelog, epoch), 0o644),
        "usr/share/doc/rdappy/README.md.gz": (gzip_bytes((ROOT / "README.md").read_bytes(), epoch), 0o644),
    }
    size = sum((len(content) + 1023) // 1024 for content, _ in data.values())
    control = (f"Package: rdappy\nVersion: {release}\nArchitecture: all\nSection: net\nPriority: optional\n"
               "Maintainer: koorg <koorg@users.noreply.github.com>\n"
               f"Installed-Size: {size}\nDepends: python3 (>= 3.10)\n"
               "Homepage: https://github.com/koorg/rdappy\n"
               "Description: client RDAP en français, en un seul fichier Python\n"
               " Interroge domaines, réseaux IP et systèmes autonomes avec la\n"
               " bibliothèque standard. Résumé des organisations titulaires inclus.\n").encode("utf-8")
    md5 = "".join(f"{hashlib.md5(content, usedforsecurity=False).hexdigest()}  {name}\n" for name, (content, _) in sorted(data.items())).encode("ascii")
    parts = [("debian-binary", b"2.0\n"),
             ("control.tar.gz", deb_tar({"control": (control, 0o644), "md5sums": (md5, 0o644)}, epoch)),
             ("data.tar.gz", deb_tar(data, epoch))]
    result = bytearray(b"!<arch>\n")
    for name, content in parts:
        header = f"{name:<16}{epoch:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}`\n".encode("ascii")
        assert len(header) == 60
        result.extend(header)
        result.extend(content)
        if len(content) % 2:
            result.extend(b"\n")
    path = Path(output) / f"rdappy_{release}_all.deb"
    path.write_bytes(result)
    return path


def build(output, epoch):
    try:
        installed = version("setuptools")
    except PackageNotFoundError:
        installed = "not installed"
    if installed != BACKEND_VERSION:
        raise RuntimeError(f"This build requires setuptools=={BACKEND_VERSION}; found {installed}. No dependency was downloaded.")
    if not 315532800 <= epoch <= 4354819199:
        raise RuntimeError("SOURCE_DATE_EPOCH must fall between 1980 and 2107.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["SOURCE_DATE_EPOCH"] = str(epoch)
    os.environ["PYTHONHASHSEED"] = "0"
    from setuptools import build_meta

    previous = Path.cwd()
    try:
        os.chdir(ROOT)
        # The backend is invoked directly: no installer, resolver or network.
        with tempfile.TemporaryDirectory(prefix=".rdappy-build-", dir=output) as temporary:
            wheel = Path(temporary) / build_meta.build_wheel(temporary)
            sdist = Path(temporary) / build_meta.build_sdist(temporary)
            expected = application_version()
            if wheel.name != f"rdappy-{expected}-py3-none-any.whl" or sdist.name != f"rdappy-{expected}.tar.gz":
                raise RuntimeError("Package metadata and application versions do not match.")
            normalize_wheel(wheel, epoch)
            normalize_sdist(sdist, epoch)
            artifacts = [output / wheel.name, output / sdist.name]
            os.replace(wheel, artifacts[0])
            os.replace(sdist, artifacts[1])
        standalone = output / "rdappy.py"
        standalone.write_bytes((ROOT / "rdappy.py").read_bytes())
        artifacts.append(standalone)
        artifacts.append(build_deb(output, epoch))
        checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(artifacts))
        (output / "SHA256SUMS").write_text(checksums, encoding="ascii", newline="\n")
        return artifacts
    finally:
        os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist", help="destination for archives and SHA256SUMS")
    parser.add_argument("--deb-only", action="store_true", help="build only the Debian package using the standard library")
    args = parser.parse_args()
    try:
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))
        if not 315532800 <= epoch <= 4354819199:
            raise RuntimeError("SOURCE_DATE_EPOCH must fall between 1980 and 2107.")
        if args.deb_only:
            args.output.mkdir(parents=True, exist_ok=True)
            artifacts = [build_deb(args.output, epoch)]
        else:
            artifacts = build(args.output, epoch)
        for artifact in artifacts:
            print(artifact)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
