#!/usr/bin/env python3
"""Build reproducible wheel/source archives using the pinned local backend."""

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

BACKEND_VERSION = "82.0.1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPOCH = int(datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp())


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
        checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(artifacts))
        (output / "SHA256SUMS").write_text(checksums, encoding="ascii", newline="\n")
        return artifacts
    finally:
        os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist", help="destination for archives and SHA256SUMS")
    args = parser.parse_args()
    try:
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))
        for artifact in build(args.output, epoch):
            print(artifact)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
