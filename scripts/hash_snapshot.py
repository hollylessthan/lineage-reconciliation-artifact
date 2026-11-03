#!/usr/bin/env python3
"""Generate or verify SHA-256 hashes for tracked release files, excluding itself."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "docs/SNAPSHOT_SHA256.json"

def inventory(output):
    output = output.resolve()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    files = {}
    for name in sorted(p.decode("utf-8") for p in paths if p):
        path = ROOT / name
        if path.resolve() == output:
            continue
        if not path.is_file():
            raise RuntimeError("Missing tracked file: " + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": "artifact-files-sha256/v1", "files": files}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    expected = inventory(output)
    if args.check:
        recorded = json.loads(output.read_text())
        if recorded != expected:
            missing = set(expected["files"]) - set(recorded.get("files", {}))
            extra = set(recorded.get("files", {})) - set(expected["files"])
            changed = sorted(k for k in expected["files"] if k in recorded.get("files", {}) and recorded["files"][k] != expected["files"][k])
            raise SystemExit(f"SHA-256 inventory mismatch: missing={sorted(missing)}, extra={sorted(extra)}, changed={changed}")
        print(f"PASS: {len(expected['files'])} tracked file checksums")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {len(expected['files'])} tracked file hashes: {output}")

if __name__ == "__main__":
    main()
