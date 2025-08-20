import argparse
from commit_rewriter import rewrite_commits

def main():
    parser = argparse.ArgumentParser(description="Rewrite commit messages with AI")
    parser.add_argument("--n", type=int, default=5, help="Number of commits to rewrite")
    parser.add_argument("--base", default="HEAD", help="Base revision")
    parser.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    args = parser.parse_args()

    if args.mode == "dry-run":
        print("DRY RUN MODE - Messages will be shown but not applied\\n")
        rewrite_commits(args.n, args.base)
    else:
        # Apply mode will require additional git operations
        raise NotImplementedError("Apply mode not implemented yet")

if __name__ == "__main__":
    main()