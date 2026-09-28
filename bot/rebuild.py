# -*- coding: utf-8 -*-
"""Rebuild the day's content with the current renderer. Never publishes.

    python rebuild.py            # 3 posts + 3 reels
    python rebuild.py 3 0        # 3 posts, no reels
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# hard off-switches: this script exists so a rebuild can never post anything
os.environ["DRY_RUN"] = "1"
os.environ["APPROVED"] = "0"
os.environ.setdefault(
    "OUT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "out"))

import pipeline  # noqa: E402


def main() -> int:
    posts = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    reels = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"rebuild: posts={posts} reels={reels} publish=False", flush=True)
    res = pipeline.run(posts=posts, reels=reels, publish=False)
    errs = res.get("errors") or []
    print(f"\nposts made : {len(res['posts'])}")
    print(f"reels made : {len(res['reels'])}")
    print(f"skipped    : {len(res['skipped'])}")
    print(f"errors     : {len(errs)}")
    for e in errs:
        print(f"  !! {e}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
