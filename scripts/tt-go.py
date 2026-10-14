#!/usr/bin/env python3
"""thinktank wrapper: estimate first, run only on explicit confirmation.

Stone's rule (2026-10-14): every thinktank run must show the estimate
(models / API calls / cost cap / time) BEFORE running, and only run
after he replies go/change. This wrapper makes skipping impossible.

Usage:
  tt-go.py ask --models ... --judge-model ... [other thinktank args] "question"
    -> prints estimate, then asks: type 'go' to run, anything else aborts.

  tt-go.py --yes ask ... "question"
    -> skips interactive prompt (for standing tasks / already-approved runs).
       The estimate is still printed first.

The wrapper passes all args through to thinktank.py unchanged, except it
runs with --estimate first, then re-runs without it after confirmation.
"""
import os
import subprocess
import sys

THINKTANK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thinktank.py")


def main():
    args = sys.argv[1:]
    auto = False
    if args and args[0] == "--yes":
        auto = True
        args = args[1:]

    if not args:
        print("usage: tt-go.py [--yes] ask ... \"question\"", file=sys.stderr)
        sys.exit(2)

    # Step 1: always print estimate first
    est = subprocess.run(
        [sys.executable, THINKTANK] + args + ["--estimate"],
        capture_output=True, text=True,
    )
    print(est.stdout, end="")
    if est.stderr:
        print(est.stderr, end="", file=sys.stderr)
    if est.returncode != 0:
        print("[tt-go] estimate failed, refusing to run.", file=sys.stderr)
        sys.exit(est.returncode)

    # Step 2: confirmation gate
    if auto:
        print("[tt-go] --yes: estimate shown above, proceeding.")
    else:
        try:
            ans = input("[tt-go] Reply 'go' to run, anything else aborts: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("go", "g", "去", "好的", "ok"):
            print("[tt-go] aborted, nothing ran.")
            sys.exit(0)

    # Step 3: run for real
    print("[tt-go] running...")
    r = subprocess.run([sys.executable, THINKTANK] + args)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
