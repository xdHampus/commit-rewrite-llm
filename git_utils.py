import subprocess
from typing import List, Dict

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

def commit_with_message(sha: str, new_message: str) -> str:
    # Amend last commit with new message
    subprocess.run(["git", "commit", "--amend", "-m", new_message], check=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return result.stdout.strip()