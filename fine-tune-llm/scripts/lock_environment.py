"""Resolve one host's full binary closure, then produce a hash-required install lock.

No model/data downloads or training. Resolution does not install packages. A lock
is candidate evidence until pip check plus the separately invoked checks pass.
"""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--from-report", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new lock output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.output.with_suffix(".resolution.json")
    if args.from_report:
        report_path = args.from_report
    else:
        subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--only-binary=:all:",
                        "--report", str(report_path), "-r", str(args.requirements)], check=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entries = []
    packages = {}
    for entry in report["install"]:
        info = entry["download_info"]
        url, hashes = info["url"], info["archive_info"]["hashes"]
        if urlparse(url).hostname not in {"files.pythonhosted.org", "download.pytorch.org", "download-r2.pytorch.org"} or \
                not urlparse(url).path.endswith(".whl") or "sha256" not in hashes:
            raise ValueError("Only hashed official PyPI/PyTorch binary wheels are accepted")
        metadata = entry["metadata"]
        packages[metadata["name"]] = metadata["version"]
        entries.append(f"{metadata['name']} @ {url} --hash=sha256:{hashes['sha256']}")
    args.output.write_text("# Candidate lock; no execution qualification implied\n" + "\n".join(sorted(entries)) + "\n", encoding="utf-8")
    args.output.with_suffix(".manifest.json").write_text(json.dumps({
        "schema": "lifemate-platform-lock-v1", "profile": args.profile, "platform": platform.platform(),
        "python": sys.version, "machine": platform.machine(), "environment": report["environment"],
        "requirements_sha256": hashlib.sha256(args.requirements.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "resolution_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "wheels": len(entries), "packages": packages, "compatibility": "not_run"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
