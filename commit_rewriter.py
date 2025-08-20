import json
import os
from typing import List
from datetime import datetime
import subprocess
import tempfile
from ai_client import get_ai_response
from git_utils import get_commits, get_diff

CHECKPOINT_FILE = ".git-rewrite-ai/checkpoint.json"
METADATA_DIR = ".git-rewrite-ai"

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Corrupted checkpoint file: {e}")
    return {}

def save_checkpoint(data):
    os.makedirs(METADATA_DIR, exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def summarize_diff(diff: str, chunk_size: int = 8000, max_total: int = 160000) -> str:
    """Intelligently summarize a large diff by processing it in chunks"""
    
    # If diff is small enough, return as-is
    if len(diff) <= chunk_size:
        return diff
    
    # Truncate if exceeds max total
    if len(diff) > max_total:
        diff = diff[:max_total] + "\n... (diff truncated)"
    
    lines = diff.split('\n')
    
    # Split diff into logical chunks (by file boundaries or size)
    chunks = []
    current_chunk = []
    current_size = 0
    
    for line in lines:
        current_chunk.append(line)
        current_size += len(line)
        
        # Split if chunk reaches size limit
        if current_size >= chunk_size:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_size = 0
    
    # Add final chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    # If only one chunk, return it
    if len(chunks) == 1:
        return chunks[0]
    
    print(f"  Processing {len(chunks)} chunks of diff...")
    
    # Summarize each chunk
    summaries = []
    for i, chunk in enumerate(chunks):
        if "... (diff truncated)" in chunk:
            summaries.append("... (additional changes truncated)")
            continue
            
        # Get AI to summarize this chunk
        chunk_prompt = (
            "Summarize this code diff chunk in 3-4 bullet points. "
            "Focus on WHAT changed (files, functions, logic), and WHY it matters:\n\n"
            f"{chunk[:chunk_size]}"
        )
        
        summary = get_ai_response(chunk_prompt, max_tokens=600)
        if summary:
            summaries.append(f"=== Part {i+1} ===\n{summary}")
        else:
            # Fallback to basic extraction if AI fails
            file_names = [line.split()[-1] for line in chunk.split('\n') if line.startswith('+++')]
            summaries.append(f"=== Part {i+1} ===\n- Changes to: {', '.join(file_names[:3])}")
    
    # Combine all summaries
    combined_summary = "\n\n".join(summaries)
    
    # If combined summaries are still too long, create a meta-summary
    if len(combined_summary) > chunk_size:
        print("  Creating meta-summary of all chunks...")
        meta_prompt = (
            "Combine these diff summaries into a cohesive overview. "
            "Group related changes and highlight the main purpose:\n\n"
            f"{combined_summary[:chunk_size*2]}"
        )
        combined_summary = get_ai_response(meta_prompt, max_tokens=700)
    
    return combined_summary

def generate_commit_message(diff: str, history_summary: str) -> str:
    """Generate a commit message from a diff, handling large diffs intelligently"""
    
    diff_size = len(diff)
    
    # For very large diffs, use intelligent summarization
    if diff_size > 1000000:
        print(f"  Diff size: {diff_size:,} chars")
        summarized_diff = summarize_diff(diff, chunk_size=1000000, max_total=6000000)
        
        prompt = (
            "Generate a professional commit message for these code changes.\n"
            f"Previous 3 commits:\n{history_summary}\n\n"
            "=== CHANGES ===\n"
            f"{summarized_diff}\n\n"
            "Requirements:\n"
            "- Use conventional commit format: type(scope): description\n"
            "- Title max 72 chars, be specific\n"
            "- Body should explain the key changes and motivation\n"
            "- Max 500 chars in body\n"
            "- Focus on the WHY and WHAT, not implementation details"
        )
    else:
        # Small diff - use directly
        prompt = (
            "Generate a professional commit message for this code change.\n"
            f"Previous 3 commits:\n{history_summary}\n\n"
            f"=== DIFF ===\n{diff}\n\n"
            "Requirements:\n"
            "- Use conventional commit format: type(scope): description\n"
            "- Title max 72 chars\n"
            "- Body explains key changes\n"
            "- Max 500 chars in body"
        )
    
    return get_ai_response(prompt, max_tokens=300) or "chore: update code"

def get_base_commit(commits: List[dict]) -> str:
    """Get the base commit (one before the oldest commit we're rewriting)"""
    oldest_sha = commits[0]['sha']
    result = subprocess.run(
        ["git", "rev-parse", f"{oldest_sha}~1"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()

def escape_commit_message_for_shell(message: str) -> str:
    """Escape commit message for shell execution"""
    # Replace single quotes with '\'' and escape backslashes
    return message.replace("\\", "\\\\").replace("'", "'\\''")

def create_bash_exec_script(commits_with_messages: List[tuple]) -> str:
    """Create a standalone bash script to rewrite commits using rebase with exec"""
    script_lines = []
    
    # Add shebang and header
    script_lines.append("#!/bin/bash")
    script_lines.append("")
    script_lines.append("# Standalone script to rewrite commit messages")
    script_lines.append("# This script creates a rebase todo file and executes it")
    script_lines.append("")
    script_lines.append("set -e  # Exit on error")
    script_lines.append("")
    
    # Get the base commit
    script_lines.append("# Find the base commit for rebase")
    oldest_sha = commits_with_messages[0][0]
    script_lines.append(f"BASE_COMMIT=$(git rev-parse {oldest_sha}~1)")
    script_lines.append('echo "Base commit: $BASE_COMMIT"')
    script_lines.append("")
    
    # Create a temporary file for the rebase todo
    script_lines.append("# Create temporary rebase todo file")
    script_lines.append('REBASE_TODO=$(mktemp /tmp/git-rebase-todo.XXXXXX)')
    script_lines.append('echo "Creating rebase todo at: $REBASE_TODO"')
    script_lines.append("")
    
    # Write the rebase todo content
    script_lines.append("# Write rebase todo content")
    script_lines.append('cat > "$REBASE_TODO" << \'EOF\'')
    
    # Add pick + exec for each commit
    for sha, new_message in commits_with_messages:
        summary = new_message.split('\n')[0] if new_message else "update"
        script_lines.append(f"pick {sha} {summary}")
        
        # Escape the message for shell
        escaped_message = escape_commit_message_for_shell(new_message)
        script_lines.append(f"exec git commit --amend --no-edit -m '{escaped_message}'")
        script_lines.append("")
    
    script_lines.append("EOF")
    script_lines.append("")
    
    # Execute the rebase
    script_lines.append("# Execute the rebase")
    script_lines.append('echo "Starting rebase..."')
    script_lines.append('GIT_SEQUENCE_EDITOR="cat \\"$REBASE_TODO\\"" git rebase -i "$BASE_COMMIT"')
    script_lines.append("")
    
    # Cleanup
    script_lines.append("# Cleanup")
    script_lines.append('rm -f "$REBASE_TODO"')
    script_lines.append('echo "✅ All commits have been updated!"')
    
    return '\n'.join(script_lines)

def create_filter_branch_script(commits_with_messages: List[tuple]) -> str:
    """Create a bash script using git filter-branch to rewrite history"""
    script_lines = []
    
    # Add shebang and header
    script_lines.append("#!/bin/bash")
    script_lines.append("")
    script_lines.append("# Script to rewrite commit messages using filter-branch")
    script_lines.append("# WARNING: This rewrites history for all matching commits")
    script_lines.append("")
    script_lines.append("set -e  # Exit on error")
    script_lines.append("")
    
    # Get the starting point
    oldest_sha = commits_with_messages[0][0]
    script_lines.append(f"# Rewriting from commit {oldest_sha[:8]}")
    script_lines.append("")
    
    # Create temporary directory for messages
    script_lines.append("# Create temp directory for messages")
    script_lines.append('TMPDIR=$(mktemp -d)')
    script_lines.append('echo "Using temp directory: $TMPDIR"')
    script_lines.append("")
    
    # Write each message to a file
    for sha, new_message in commits_with_messages:
        script_lines.append(f"# Message for {sha[:8]}")
        script_lines.append(f"cat > \"$TMPDIR/{sha}\" << 'EOF'")
        script_lines.append(new_message)
        script_lines.append("EOF")
        script_lines.append("")
    
    # Create the filter-branch command
    script_lines.append("# Run filter-branch")
    script_lines.append("git filter-branch -f --msg-filter '")
    script_lines.append("commit_sha=$(git rev-parse $GIT_COMMIT)")
    script_lines.append(f"if [ -f \"$TMPDIR/$commit_sha\" ]; then")
    script_lines.append(f"  cat \"$TMPDIR/$commit_sha\"")
    script_lines.append("else")
    script_lines.append("  cat  # Keep original message")
    script_lines.append("fi")
    script_lines.append(f"' {oldest_sha}~1..HEAD")
    script_lines.append("")
    
    # Cleanup
    script_lines.append("# Cleanup")
    script_lines.append('rm -rf "$TMPDIR"')
    script_lines.append("")
    script_lines.append('echo "✅ History rewritten successfully!"')
    script_lines.append('echo "⚠️  Original refs backed up in .git/refs/original/"')
    script_lines.append('echo "To remove backups: git update-ref -d refs/original/refs/heads/$(git branch --show-current)"')
    
    return '\n'.join(script_lines)

def create_rebase_exec_script(commits_with_messages: List[tuple]) -> str:
    """Create interactive rebase script with exec commands to amend commits"""
    script_lines = []
    
    # Add header comments
    script_lines.append("# Interactive rebase script with exec amend commands")
    script_lines.append("# This script uses exec to amend each commit with new messages")
    script_lines.append("#")
    script_lines.append("# Commands:")
    script_lines.append("# pick <commit> = use commit")
    script_lines.append("# exec <command> = run shell command")
    script_lines.append("#")
    script_lines.append("")
    
    # Add pick + exec for each commit (oldest first)
    for sha, new_message in commits_with_messages:
        # Use first line of message as the commit summary
        summary = new_message.split('\n')[0] if new_message else "update"
        script_lines.append(f"pick {sha} {summary}")
        
        # Escape the message for shell
        escaped_message = escape_commit_message_for_shell(new_message)
        
        # Add exec command to amend the commit
        script_lines.append(f"exec git commit --amend --no-edit -m '{escaped_message}'")
        script_lines.append("")
    
    return '\n'.join(script_lines)

def create_rebase_script(commits_with_messages: List[tuple]) -> str:
    """Create interactive rebase script with reword commands"""
    script_lines = []
    
    # Add header comments
    script_lines.append("# Interactive rebase script generated by AI commit rewriter")
    script_lines.append("#")
    script_lines.append("# Commands:")
    script_lines.append("# p, pick <commit> = use commit")
    script_lines.append("# r, reword <commit> = use commit, but edit the commit message")
    script_lines.append("#")
    script_lines.append("# These lines can be re-ordered; they are executed from top to bottom.")
    script_lines.append("#")
    script_lines.append("")
    
    # Add reword commands for each commit (oldest first)
    for sha, new_message in commits_with_messages:
        # Use first line of message as the commit summary
        summary = new_message.split('\n')[0] if new_message else "update"
        script_lines.append(f"reword {sha} {summary}")
    
    return '\n'.join(script_lines)

def create_message_files(commits_with_messages: List[tuple]) -> str:
    """Create individual message files for each commit"""
    messages_dir = os.path.join(METADATA_DIR, "messages")
    os.makedirs(messages_dir, exist_ok=True)
    
    for sha, new_message in commits_with_messages:
        message_file = os.path.join(messages_dir, f"{sha}.msg")
        with open(message_file, 'w') as f:
            f.write(new_message)
    
    return messages_dir

def create_message_editor_script(messages_dir: str) -> str:
    """Create a script that automatically provides commit messages"""
    editor_script = f'''#!/bin/bash
# Auto-commit message editor script

# The commit message file is passed as $1
commit_file="$1"

# Extract commit SHA from the rebase directory structure
# Git creates files like: .git/rebase-merge/msgnum
if [[ "$commit_file" == */.git/rebase-*/message ]]; then
    # For newer git versions
    commit_sha=$(cat "$(dirname "$commit_file")/commit")
elif [[ "$commit_file" == */.git/rebase-*/done ]]; then
    # Extract from done file
    commit_sha=$(tail -n 1 "$(dirname "$commit_file")/done" | awk '{{print $2}}')
else
    # Try to extract SHA from filename or path
    commit_sha=$(basename "$(dirname "$commit_file")")
fi

# Try to find message file
message_file="{messages_dir}/$commit_sha.msg"
if [ ! -f "$message_file" ]; then
    # Try without .msg extension
    message_file="{messages_dir}/$commit_sha"
fi

if [ -f "$message_file" ]; then
    cat "$message_file" > "$commit_file"
    echo "Auto-filled message for $commit_sha" >&2
else
    echo "No custom message found for $commit_sha, keeping original" >&2
fi
'''
    return editor_script

def apply_rebase_automatically(commits_with_messages: List[tuple], base_commit: str, use_exec: bool = False):
    """Automatically apply the rebase with automated message editing or bash script"""
    
    if use_exec:
        # Use standalone bash script approach
        bash_script = create_bash_exec_script(commits_with_messages)
        script_path = os.path.join(METADATA_DIR, "rewrite-commits.sh")
        
        with open(script_path, 'w') as f:
            f.write(bash_script)
        os.chmod(script_path, 0o755)
        
        print(f"\n🚀 Executing bash script to rewrite commits...")
        print(f"Script saved at: {script_path}")
        print(f"Base commit: {base_commit}")
        print(f"Commits to rewrite: {len(commits_with_messages)}")
        
        try:
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                print("✅ Successfully rewrote all commits!")
                print("✨ Commit messages have been updated")
            else:
                print("❌ Script failed:")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                print("\n🔧 You can manually run the script:")
                print(f"   bash {script_path}")
                
        except Exception as e:
            print(f"❌ Error executing script: {e}")
            print(f"\n🔧 Try running manually:")
            print(f"   bash {script_path}")
    else:
        # Use traditional reword approach with temp directory
        temp_dir = tempfile.mkdtemp(prefix="git-rewrite-ai-")
        messages_dir = os.path.join(temp_dir, "messages")
        os.makedirs(messages_dir, exist_ok=True)
        
        # Create message files
        for sha, new_message in commits_with_messages:
            message_file = os.path.join(messages_dir, f"{sha}.msg")
            with open(message_file, 'w') as f:
                f.write(new_message)
        
        print(f"\n🚀 Starting automated rebase...")
        print(f"Base commit: {base_commit}")
        print(f"Commits to rewrite: {len(commits_with_messages)}")
        print(f"Method: reword")
        
        # Create editor script
        editor_script_content = create_message_editor_script(messages_dir)
        editor_script_path = os.path.join(temp_dir, "auto-editor.sh")
        with open(editor_script_path, 'w') as f:
            f.write(editor_script_content)
        os.chmod(editor_script_path, 0o755)
        
        # Create the rebase script content
        rebase_script_content = create_rebase_script(commits_with_messages)
        rebase_script_path = os.path.join(temp_dir, "rebase-script")
        with open(rebase_script_path, 'w') as f:
            f.write(rebase_script_content)
        
        # Set environment variables for automated rebase
        env = os.environ.copy()
        env['GIT_EDITOR'] = editor_script_path
        env['GIT_SEQUENCE_EDITOR'] = f"cat {rebase_script_path}"
        
        try:
            # Start the rebase
            print("Executing: git rebase -i", base_commit)
            result = subprocess.run(
                ["git", "rebase", "-i", base_commit],
                env=env,
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                print("✅ Successfully completed automated rebase!")
                print("✨ Commit messages have been rewritten automatically")
            else:
                print("⚠️  Rebase completed with some issues:")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                print("\n🔧 If rebase is still in progress, you can:")
                print("   1. Continue: git rebase --continue")
                print("   2. Abort: git rebase --abort")
                
        except subprocess.CalledProcessError as e:
            print("❌ Automated rebase failed:")
            print("Error:", e)
            print("STDOUT:", e.stdout if hasattr(e, 'stdout') else "N/A")
            print("STDERR:", e.stderr if hasattr(e, 'stderr') else "N/A")
            print("\n🔧 To manually complete the rebase:")
            print(f"   cd {temp_dir}")
            print(f"   export GIT_EDITOR={editor_script_path}")
            print(f"   git rebase --continue")
        
        except Exception as e:
            print("❌ Unexpected error during rebase:")
            print("Error:", str(e))
            
        finally:
            # Keep temporary files for debugging
            print(f"\n📁 Temporary files kept at: {temp_dir}")
            print("🗑️  To clean up later, run: rm -rf", temp_dir)


def rewrite_commits(n: int, base: str = "HEAD", mode: str = "dry-run", run_rebase: bool = False, use_exec: bool = False):
    # Get commits in correct order (oldest first)
    commits = list(reversed(get_commits(n, base)))
    checkpoint = load_checkpoint()
    
    completed_messages = checkpoint.get("completed_messages", {})
    
    history_entries = []
    for sha, msg in list(completed_messages.items())[-3:]:
        short_sha = sha[:8]
        history_entries.append(f"{short_sha} {msg}")
    history_summary = "\n".join(history_entries)

    commits_with_messages = []
    
    try:
        # Generate all messages first
        for i, commit in enumerate(commits):
            print(f"[{i+1}/{len(commits)}] Processing {commit['sha'][:8]}...")

            # Check for cached message
            if commit['sha'] in completed_messages:
                new_msg = completed_messages[commit['sha']]
                print(f"  Reusing cached message: {new_msg[:60]}...")
            else:
                print("  Generating new message...")
                diff = get_diff(commit['sha'])
                new_msg = generate_commit_message(diff, history_summary)
                
                if mode == "dry-run":
                    print(f"  Old: {commit['message']}")
                    print(f"  New: {new_msg}\n")

            # Update history context
            if len(history_entries) >= 3:
                history_entries.pop(0)
            history_entries.append(f"{commit['sha'][:8]} {new_msg}")
            history_summary = "\n".join(history_entries)
            
            # Store for rebase script
            commits_with_messages.append((commit['sha'], new_msg))
            
            # Update cache
            completed_messages[commit['sha']] = new_msg
            checkpoint_data = {
                "completed_messages": completed_messages,
                "history_summary": history_summary,
            }
            save_checkpoint(checkpoint_data)
        
        # Apply mode - handle rebase
        if mode == "apply":
            if run_rebase:
                # Automatically run rebase
                base_commit = get_base_commit(commits)
                apply_rebase_automatically(commits_with_messages, base_commit, use_exec=use_exec)
            else:
                # Just generate files for manual use
                print("\n" + "="*60)
                print("SCRIPTS GENERATED")
                print("="*60)
                
                # Get base commit
                base_commit = get_base_commit(commits)
                
                # Create all script variants
                rebase_script = create_rebase_script(commits_with_messages)
                rebase_exec_script = create_rebase_exec_script(commits_with_messages)
                bash_script = create_bash_exec_script(commits_with_messages)
                filter_script = create_filter_branch_script(commits_with_messages)
                
                # Save all scripts
                script_path = os.path.join(METADATA_DIR, "rebase-script.txt")
                exec_script_path = os.path.join(METADATA_DIR, "rebase-exec-script.txt")
                bash_script_path = os.path.join(METADATA_DIR, "rewrite-commits.sh")
                filter_script_path = os.path.join(METADATA_DIR, "filter-branch-rewrite.sh")
                
                with open(script_path, 'w') as f:
                    f.write(rebase_script)
                
                with open(exec_script_path, 'w') as f:
                    f.write(rebase_exec_script)
                
                with open(bash_script_path, 'w') as f:
                    f.write(bash_script)
                os.chmod(bash_script_path, 0o755)
                
                with open(filter_script_path, 'w') as f:
                    f.write(filter_script)
                os.chmod(filter_script_path, 0o755)
                
                # Create message files
                messages_dir = create_message_files(commits_with_messages)
                
                print(f"\n✅ Scripts created:")
                print(f"  • Rebase script (reword): {script_path}")
                print(f"  • Rebase script (exec): {exec_script_path}")
                print(f"  • Standalone bash script: {bash_script_path}")
                print(f"  • Filter-branch script: {filter_script_path}")
                print(f"  • Message files: {messages_dir}")
                
                print(f"\n🔧 METHOD 1: Standalone bash script (RECOMMENDED):")
                print(f"   bash {bash_script_path}")
                
                print(f"\n🔧 METHOD 2: Using rebase with exec:")
                print(f"   export GIT_SEQUENCE_EDITOR='cat {exec_script_path}'")
                print(f"   git rebase -i {base_commit}")
                
                print(f"\n🔧 METHOD 3: Using rebase with reword:")
                print(f"   export GIT_SEQUENCE_EDITOR='cat {script_path}'")
                print(f"   git rebase -i {base_commit}")
                
                print(f"\n🔧 METHOD 4: Using filter-branch (rewrites entire history):")
                print(f"   bash {filter_script_path}")
                
                print(f"\n📝 For fully automated execution, use:")
                print(f"   --run flag (uses reword method)")
                print(f"   --run --exec flag (uses standalone bash script)")
                
                # Show sample of bash script
                print(f"\n📄 BASH SCRIPT PREVIEW:")
                print("-" * 40)
                bash_lines = bash_script.split('\n')
                for i, line in enumerate(bash_lines[:30]):
                    print(line)
                if len(bash_lines) > 30:
                    print("... (truncated)")
                print("-" * 40)
            
    except Exception as e:
        print(f"Error during processing: {e}")
        raise