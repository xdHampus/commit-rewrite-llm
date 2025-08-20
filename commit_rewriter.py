import json
import os
from typing import List
from ai_client import get_ai_response
from git_utils import get_commits, get_diff

CHECKPOINT_FILE = ".git-rewrite-ai/checkpoint.json"

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_checkpoint(data):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def summarize_diff(diff: str, max_lines: int = 80000) -> str:
    """Extract and summarize key parts of a large diff"""
    lines = diff.split('\n')
    
    # Limit total lines
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("\\n... (diff truncated)")
    
    # Join and truncate to token limit
    combined = '\\n'.join(lines)
    return combined[:8000]  # Truncate to API limit

def generate_commit_message(diff: str, history_summary: str) -> str:
    summarized_diff = summarize_diff(diff)
    
    prompt = (
        "You are producing a concise commit message for a code change.\\n"
        f"Project history context (last 3 changes):\\n{history_summary}\\n\\n"
        f"Current diff:\\n{summarized_diff}\\n\\n"
        "Respond only with a conventional commit message like:\\n"
        "feat(api): add user authentication endpoint\\n\\n"
        "Fixes #123\\n\\n"
        "Max 72 characters in title. Max 500 in body."
    )
    return get_ai_response(prompt, max_tokens=250) or "chore: update code"

def rewrite_commits(n: int, base: str = "HEAD"):
    commits = get_commits(n, base)
    checkpoint = load_checkpoint()
    start_idx = checkpoint.get("last_index", -1) + 1
    
    # Build history from both completed commits and original ones
    history_entries = []
    for i in range(min(3, start_idx)):  # Last 3 entries
        if i < len(commits):
            commit = commits[i]
            if "completed_messages" in checkpoint:
                msg = checkpoint["completed_messages"].get(commit['sha'], commit['message'])
            else:
                msg = commit['message']
            history_entries.append(f"{commit['sha'][:8]} {msg}")
    
    history_summary = "\\n".join(history_entries)

    # Track completed messages for context in this run
    completed_messages = checkpoint.get("completed_messages", {})
    
    for i in range(start_idx, len(commits)):
        commit = commits[i]
        diff = get_diff(commit['sha'])
        new_msg = generate_commit_message(diff, history_summary)
        
        print(f"[{i+1}/{len(commits)}] {commit['sha'][:8]}:\\nOld: {commit['message']}\\nNew: {new_msg}\\n")
        
        # Update context for next commits
        if len(history_entries) >= 3:
            history_entries.pop(0)
        history_entries.append(f"{commit['sha'][:8]} {new_msg}")
        history_summary = "\\n".join(history_entries)
        
        # Save progress
        completed_messages[commit['sha']] = new_msg
        checkpoint.update({
            "last_index": i,
            "last_commit": commit['sha'],
            "new_message": new_msg,
            "history_summary": history_summary,
            "completed_messages": completed_messages
        })
        save_checkpoint(checkpoint)

if __name__ == "__main__":
    rewrite_commits(5)  # Rewrite last 5 commits