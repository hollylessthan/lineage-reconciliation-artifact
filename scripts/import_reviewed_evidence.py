#!/usr/bin/env python3
"""Import the reviewed Spark and zero-dependency compiler evidence ZIP.

Run on a local checkout of the artifact PR branch:
    python scripts/import_reviewed_evidence.py /path/to/lineage-evidence-reviewed.zip

Checks every listed SHA-256 and rejects unexpected entries, archive traversal,
duplicate destinations, or existing files with different bytes.
This script does not push to GitHub or publish the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
MAP = {"compiler/": "evidence/compiler/", "spark/": "evidence/probes/spark/"}
META = {"SHA256.json", "REDACTION_REVIEW.md"}


def import_archive(archive):
    with ZipFile(archive) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive member")
        expected = json.loads(z.read("SHA256.json"))["sha256"]
        if set(names) != set(expected) | META:
            raise ValueError("Unexpected or missing archived files")
        pending = []
        for name, digest in sorted(expected.items()):
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or not any(name.startswith(prefix) for prefix in MAP):
                raise ValueError("Unsafe archive member: " + name)
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Checksum mismatch: " + name)
            prefix = next(k for k in MAP if name.startswith(k))
            dest = ROOT / MAP[prefix] / name[len(prefix):]
            if dest.exists() and dest.read_bytes() != data:
                raise ValueError("Existing destination differs: " + str(dest))
            pending.append((dest, data))
        pending += [(ROOT / "evidence/import/SHA256.json", z.read("SHA256.json")),
                    (ROOT / "evidence/import/REDACTION_REVIEW.md", z.read("REDACTION_REVIEW.md"))]
        for dest, data in pending:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    print("Verified and imported", len(expected), "evidence files and two audit files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    import_archive(parser.parse_args().archive)
