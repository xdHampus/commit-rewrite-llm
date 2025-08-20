#!/usr/bin/env python3
# Save as git-reword-editor.py

import sys
import re

# Read the commit message file that git passes
commit_file = sys.argv[1]

# Read the current commit message to extract the SHA
with open(commit_file, 'r') as f:
    content = f.read()

# Extract the commit SHA from the comment lines
# Git includes the SHA in comments during reword
commit_sha = None
for line in content.split('\n'):
    if line.startswith('#') and 'reword' in line:
        parts = line.split()
        for part in parts:
            if len(part) >= 7 and all(c in '0123456789abcdef' for c in part):
                commit_sha = part[:8]  # Use first 8 chars for matching
                break

if not commit_sha:
    sys.exit(1)  # Exit if we can't find the SHA

# Parse the rebase script file to build the mapping
messages = {}
with open('.git-rewrite-ai/rebase-script.txt', 'r') as f:
    for line in f:
        if line.startswith('reword '):
            parts = line.strip().split(' ', 2)
            if len(parts) == 3:
                messages[parts[1][:8]] = parts[2]

# Write the new message if we have one
if commit_sha in messages:
    with open(commit_file, 'w') as f:
        f.write(messages[commit_sha])