import subprocess
from typing import List, Dict
import os
import shutil

def get_commits(n: int, base: str = "HEAD") -> List[Dict]:
    cmd = ["git", "log", f"-{n}", "--reverse", "--pretty=format:%H %s", base]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    lines = result.stdout.strip().split('\n')
    commits = []
    for i, line in enumerate(lines[::-1]):  # Oldest to newest
        parts = line.split(' ', 1)
        commits.append({
            'sha': parts[0],
            'message': parts[1] if len(parts) > 1 else '',
            'index': i
        })
    return commits

def get_diff(sha: str) -> str:
    cmd = ["git", "show", sha]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout

def create_branch(name: str):
    subprocess.run(["git", "checkout", "-b", name], check=True)

def backup_original_ref():
    """Backup current HEAD before rewriting"""
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    original_sha = result.stdout.strip()
    backup_ref = f"refs/original-rewrites/original-{original_sha[:8]}"
    subprocess.run(["git", "update-ref", backup_ref, original_sha], check=True)
    return original_sha, backup_ref

def apply_commit_message(new_message: str) -> str:
    print(f"Applying new commit message: {new_message}")
    result = subprocess.run(
        ["git", "commit", "--amend", "-m", new_message],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Commit amend failed:")
        print(result.stderr)
        raise RuntimeError("Commit amend failed")
    parse_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True
    )
    return parse_result.stdout.strip()

def cherry_pick_commit(sha: str):
    print(f"Cherry-picking {sha}...")
    result = subprocess.run(
        ["git", "cherry-pick", sha],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if "nothing to commit" in result.stdout or "already applied" in result.stdout:
            print("Commit already applied. Skipping.")
            return
        print("Cherry-pick failed:")
        print(result.stderr)
        raise RuntimeError("Cherry-pick failed")

def reset_to_commit(sha: str):
    """Reset branch to specific commit"""
    subprocess.run(["git", "reset", "--hard", sha], check=True)