#!/usr/bin/env python3
"""Repository-local release audit: links, stale private URLs, secrets and imports.

This is a deterministic screening tool, not legal or credential clearance.
"""
import ast
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)
TEXT = {p: p.read_text(encoding="utf-8", errors="replace") for p in FILES if p.suffix in {".py",".md",".yml",".yaml",".json",".jsonl",".toml",".txt",".tex"} or p.name in {"README.md","LICENSE"}}
ISSUES = []
PRIVATE = re.compile(r"(?i)github\.com/hollylessthan/lineage-reconciliation-study")
SECRET = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
MDLINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
for p,c in TEXT.items():
    relative = p.relative_to(ROOT).as_posix()
    if PRIVATE.search(c):
        ISSUES.append([relative,"private source URL"])
    if SECRET.search(c):
        ISSUES.append([relative,"high confidence credential pattern"])
    if relative.startswith("docs/") or relative == "README.md":
        for link in MDLINK.findall(c):
            link=link.strip().split("#",1)[0]
            if not link or link.startswith(("https://","http://","mailto:")):
                continue
            if not (p.parent / link).exists():
                ISSUES.append([relative,"broken relative link: "+link])
    if p.suffix==".py":
        try:
            tree=ast.parse(c)
        except SyntaxError as err:
            ISSUES.append([relative,"Python parse: "+str(err)])
            continue
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.level==0 and node.module:
                module=node.module.split(".")[0]
                if (ROOT/"scripts"/(module+".py")).exists() or (ROOT/"probes"/(module+".py")).exists():
                    continue
            # External packages are installed via requirements and handled by live replay.
report={"schema":"artifact-release-audit/v1","files_scanned":len(TEXT),"issues":ISSUES,
"limitations":["Regex screening does not rule out secrets encoded in novel formats or public email addresses inside third-party model metadata.","External HTTP links are inventoried, not network-verified.","Dependency installation and runtime compatibility require clean-machine replay.","Third-party datasets, source histories, and copied code need license review against their originating projects."]}
print(json.dumps(report,indent=2))
if ISSUES:
    raise SystemExit(1)
