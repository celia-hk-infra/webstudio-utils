#!/usr/bin/env python3
"""Install a checksum-verified GOST client into persistent tool storage."""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from direct_egress import config_path, proxy_environment, read_url


VERSION = "3.3.3"
BASE = f"https://github.com/go-gost/gost/releases/download/v{VERSION}"
CHUNK = 512 * 1024


def request(url, env, *options):
    result = subprocess.run(
        ["curl", "-q", "--location", "--silent", "--connect-timeout", "10",
         "--max-time", "90", *map(str, options), url],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode, result.stdout.decode(errors="replace")


def last_headers(path):
    blocks = path.read_text(errors="replace").replace("\r\n", "\n").split("\n\n")
    lines = next((block.splitlines() for block in reversed(blocks) if block.startswith("HTTP/")), [])
    values = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            values[key.lower()] = value.strip()
    status = int(lines[0].split()[1]) if lines else 0
    return status, values


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_checksum(asset, env):
    code, body = request(BASE + "/checksums.txt", env, "--fail", "--max-time", "30")
    if code:
        raise RuntimeError("Could not download GOST checksums")
    for line in body.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    raise RuntimeError("GOST asset is absent from upstream checksums")


def download_archive(asset, expected, cache, env):
    if cache.is_file() and sha256(cache) == expected:
        return cache
    local = Path(os.environ.get("WEBSTUDIO_LOCAL_DIR", f"/tmp/webstudio-{os.getuid()}"))
    local.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="gost-download-", dir=local) as directory:
        temp = Path(directory)
        head = temp / "head"
        code, final_url = request(BASE + "/" + asset, env, "--fail", "--head",
                                  "--dump-header", head, "--output", os.devnull,
                                  "--write-out", "%{url_effective}")
        status, values = last_headers(head)
        if code or status != 200:
            raise RuntimeError("Could not inspect GOST archive")
        size = int(values.get("content-length", "0"))
        if not 0 < size < 100 * 1024 * 1024:
            raise RuntimeError("Invalid GOST archive size")

        def part(start, end):
            output = temp / f"part-{start}"
            attempts = 0
            while (output.stat().st_size if output.exists() else 0) < end - start + 1:
                attempts += 1
                if attempts > 6:
                    raise RuntimeError("GOST range download failed repeatedly")
                current = start + (output.stat().st_size if output.exists() else 0)
                piece = temp / f"piece-{start}"
                headers = temp / f"headers-{start}"
                piece.unlink(missing_ok=True)
                headers.unlink(missing_ok=True)
                code, _ = request(final_url, env, "--range", f"{current}-{end}",
                                  "--dump-header", headers, "--output", piece)
                if not headers.exists():
                    continue
                status, received = last_headers(headers)
                expected_range = f"bytes {current}-{end}/{size}"
                if status != 206 or received.get("content-range") != expected_range:
                    if code:
                        continue
                    raise RuntimeError("GOST server did not honor the requested range")
                if piece.exists() and 0 < piece.stat().st_size <= end - current + 1:
                    with output.open("ab") as target, piece.open("rb") as source:
                        shutil.copyfileobj(source, target)
                elif code == 0:
                    raise RuntimeError("Invalid GOST range response")
            return output

        assembled = temp / "archive"
        if values.get("accept-ranges", "").lower() == "bytes":
            ranges = [(start, min(size - 1, start + CHUNK - 1))
                      for start in range(0, size, CHUNK)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                pieces = list(pool.map(lambda bounds: part(*bounds), ranges))
            with assembled.open("wb") as target:
                for piece in pieces:
                    with piece.open("rb") as source:
                        shutil.copyfileobj(source, target)
        else:
            code, _ = request(final_url, env, "--fail", "--max-time", "1800",
                              "--output", assembled)
            if code:
                raise RuntimeError("GOST archive download failed")
        if assembled.stat().st_size != size or sha256(assembled) != expected:
            raise RuntimeError("GOST archive failed size or SHA-256 verification")
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix=".gost-archive-", dir=cache.parent)
        try:
            with os.fdopen(fd, "wb") as target, assembled.open("rb") as source:
                shutil.copyfileobj(source, target)
            os.replace(staged, cache)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)
    return cache


def main():
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    if arch is None:
        raise RuntimeError("Direct GOST installer supports x86_64 and aarch64")
    asset = f"gost_{VERSION}_linux_{arch}.tar.gz"
    state = Path(os.environ["WEBSTUDIO_AGENT_STATE_DIR"])
    root = Path(os.environ.get("WEBSTUDIO_PERSIST_ROOT", str(state.parent)))
    target = root / "tools/gost" / VERSION / "bin/gost"
    if target.is_file() and os.access(target, os.X_OK):
        result = subprocess.run([str(target), "-V"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, check=False)
        if result.returncode == 0 and result.stdout.startswith(f"gost {VERSION} "):
            print(f"GOST {VERSION} already installed")
            return
    env = proxy_environment(read_url(config_path()))
    checksum = expected_checksum(asset, env)
    archive = download_archive(asset, checksum, root / "cache/gost" / asset, env)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".gost-bin-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, tarfile.open(archive, "r:gz") as bundle:
            source = bundle.extractfile("gost")
            if source is None:
                raise RuntimeError("GOST binary missing from verified archive")
            shutil.copyfileobj(source, output)
        os.chmod(staged, 0o755)
        os.replace(staged, target)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    print(f"Installed GOST {VERSION}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, tarfile.TarError) as error:
        print(f"Direct GOST install: {error}", file=sys.stderr)
        raise SystemExit(1)
