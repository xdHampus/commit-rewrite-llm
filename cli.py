import argparse
import sys
import os
from commit_rewriter import rewrite_commits, load_checkpoint

def main():
    parser = argparse.ArgumentParser(description="Rewrite commit messages with AI")
    parser.add_argument("--n", type=int, default=5, help="Number of commits to rewrite")
    parser.add_argument("--base", default="HEAD", help="Base revision")
    parser.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--run", action="store_true", help="Actually execute the rebase (only works with --mode apply)")
    args = parser.parse_args()

    # Check for resume
    if args.resume:
        checkpoint = load_checkpoint()
        if not checkpoint:
            print("No checkpoint found. Starting fresh run.")
        else:
            print(f"Resuming from checkpoint (last processed: {checkpoint.get('last_commit', 'unknown')[:8]})")
    
    # Safety check for apply mode
    if args.mode == "apply":
        action = "generate rebase script" if not args.run else "AUTOMATICALLY EXECUTE rebase"
        print(f"WARNING: This will {action} and rewrite git history!")
        print("Make sure you are on a feature branch and have backups.")
        response = input("Continue? (type 'yes' to proceed): ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(1)

    try:
        rewrite_commits(args.n, args.base, args.mode, run_rebase=args.run)
    except KeyboardInterrupt:
        print("\nOperation interrupted. Progress saved.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()