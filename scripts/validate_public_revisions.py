"""Validate selected real revision pairs with native dbt manifests.

A parse failure is an explicit rejection, not a silently dropped observation.
No warehouse execution or cross-catalog correctness inference is made.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def run(cmd, cwd=None, timeout=150):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return {"returncode": p.returncode, "stdout_tail": p.stdout[-1200:], "stderr_tail": p.stderr[-2400:]}


def manifest_for(repo, rev, project_dir, profiles_dir):
    with tempfile.TemporaryDirectory(prefix="revision-") as tmp:
        archive = subprocess.run(["git", "-C", str(repo), "archive", rev], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if archive.returncode:
            return None, {"error": archive.stderr.decode(errors="replace")[:1000]}
        import tarfile, io
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            if any(m.issym() or m.islnk() or m.name.startswith("/") or ".." in Path(m.name).parts for m in tar.getmembers()):
                return None, {"error": "unsafe archive entries"}
            tar.extractall(tmp, filter="data")
        base = Path(tmp) / project_dir
        if not (base / "dbt_project.yml").exists():
            return None, {"error": "dbt_project.yml missing", "project_dir": project_dir}
        # Missing historical profile is an environment binding, not a dependency graph edit.
        project_yaml = base / "dbt_project.yml"
        if "profile:" not in project_yaml.read_text():
            with project_yaml.open("a") as fh: fh.write(chr(10) + "profile: default" + chr(10))
        deps = run(["dbt", "--no-version-check", "deps", "--project-dir", str(base), "--profiles-dir", str(profiles_dir)], timeout=180)
        if deps["returncode"]:
            return None, {"error": "deps_failed", "log": deps}
        parse = run(["dbt", "--no-version-check", "parse", "--no-partial-parse", "--project-dir", str(base), "--profiles-dir", str(profiles_dir)], timeout=180)
        file = base / "target" / "manifest.json"
        if parse["returncode"] or not file.exists():
            return None, {"error": "parse_failed", "log": parse}
        j = json.loads(file.read_text())
        return j, {"dbt_metadata": j.get("metadata"), "log": parse}


def identity(j, path):
    matches = [(key, n) for key, n in j["nodes"].items()
               if n.get("original_file_path") == path and n.get("resource_type") == "model"]
    if len(matches) != 1:
        return None, {"matched_nodes": len(matches)}
    key, n = matches[0]
    return {"unique_id": key, "depends_on_nodes": sorted(n.get("depends_on", {}).get("nodes", [])),
            "database": n.get("database"), "schema": n.get("schema"), "alias": n.get("alias"),
            "materialized": n.get("config", {}).get("materialized"), "enabled": n.get("config", {}).get("enabled")}, {}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--repos", required=True, type=Path)
    p.add_argument("--profiles", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args=p.parse_args()
    cases=json.loads(args.cases.read_text())
    repo_map=json.loads(args.repos.read_text())
    out=[]
    for case in cases:
        name=case["repository"]; path=case["path"]
        record={"repository":name,"path":path,"parent":case["parent"],"commit":case["commit"],"status":"rejected"}
        if case.get("change_kind")!="modified":
            record["reason"]="entity_creation_or_deletion_not_replacement";out.append(record);continue
        versions={}
        for label,rev in [("before",case["parent"]),("after",case["commit"])]:
            j, meta=manifest_for(repo_map[name]["path"],rev,repo_map[name].get("project_dir","."),args.profiles)
            if j is None: versions[label]={"error":meta};continue
            id_,detail=identity(j,path)
            versions[label]={"node":id_,"diagnostic":detail,"manifest_metadata":meta.get("dbt_metadata")}
        record["versions"]=versions
        before=versions["before"].get("node");after=versions["after"].get("node")
        if before and after:
            same_identity=all(before[k]==after[k] for k in ("unique_id","database","schema","alias","materialized"))
            old=set(before["depends_on_nodes"]);new=set(after["depends_on_nodes"])
            record["same_identity"]=same_identity
            record["added_dependencies"]=sorted(new-old)
            record["removed_dependencies"]=sorted(old-new)
            record["status"]="accepted" if same_identity and old!=new else "rejected"
            record["reason"]="accepted_compiler_dependency_change" if record["status"]=="accepted" else "identity_changed_or_no_compiler_delta"
        else:
            record["reason"]="native_manifest_missing_or_unresolved"
        out.append(record)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({"cases":out},indent=2,default=str)+"\n")
    for record in out: print(record["repository"],record["commit"][:9],record["status"],record["reason"])
    print("ACCEPTED",sum(x["status"]=="accepted" for x in out),"OF",len(out))


if __name__=="__main__":
    main()
