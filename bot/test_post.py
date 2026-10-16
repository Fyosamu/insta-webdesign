# -*- coding: utf-8 -*-
"""Local smoke test: one feed post, no publishing at all."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# never publish during a local test
os.environ["DRY_RUN"] = "1"
os.environ["APPROVED"] = "0"
os.environ.setdefault(
    "OUT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "out"))

import pipeline  # noqa: E402

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    pipeline.run(posts=n, reels=0, seed=20260926)
