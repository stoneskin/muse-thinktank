"""v0.4 module: tt/util.py."""

import sys

def log(msg):
    print("[thinktank] " + msg, file=sys.stderr, flush=True)
