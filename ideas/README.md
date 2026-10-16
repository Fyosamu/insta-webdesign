# Content idea bank

100,000 ready-to-use hooks for the website-design niche, each tagged so you
can filter it down to the one you need.

```
ideas.jsonl   100,000 lines, ~25 MB, one JSON object per line
```

## What one line looks like

```json
{"id":1,"hook":"Nobody can find your dental clinic online, and the price list is not helping.","angle":"loss","format":"reel","platform":"instagram reel","biz":"dental clinic","thing":"price list","cta":"Save this for later."}
```

| field | what it is |
|---|---|
| `hook` | the line itself - put it on screen, say it first |
| `angle` | the emotional angle (see below) - pick the one your audience responds to |
| `format` | what to make from it: reel, carousel, story set, pin, teardown... |
| `platform` | where it fits: instagram reel, tiktok, pinterest pin, youtube short... |
| `biz` | the business type it is written for |
| `thing` | the website part it is about - swap it for your own |
| `cta` | a closing line for the caption |

**20 angles:** loss, curiosity, proof, mistake, quickwin, versus, myth,
contrarian, howto, story, question, promise, warning, local, money, urgency,
secret, challenge, listicle, transformation.

## Using it

Everything runs from `bot/`:

```bash
python ideas.py find --angle loss -n 5            # five loss hooks
python ideas.py find --biz "dental" --format reel
python ideas.py find --contains "near me"
python ideas.py check                             # quality gate
python ideas.py build                             # regenerate from scratch
```

`build` is deterministic (fixed seed), so rebuilding produces the identical
file - the ids are stable across runs.

## How they are made

Not 100k rewordings of one sentence. Each idea is a hand-written template
from one angle, with two slots filled in:

    template   "Nobody can find your {biz} online, and the {thing} is not helping."
    biz        60 business types
    thing      32 website parts

All combinations are generated, de-duplicated as they go, shuffled with a
fixed seed, and the first 100,000 kept. The de-duplication is not cosmetic:
a template that is missing a slot produces the same sentence hundreds of
times, and a bank of forty sentences pretending to be a hundred thousand is
worse than no bank at all.

`check` runs before you trust the file. It fails on a hook that repeats, a
slot that did not fill, a stray double space, an `a`/`an` disagreement, or
a line long enough that it could not be shown on screen. The `a`/`an` pass
exists because templates are written with a plain `a` and most of the bank
starts with a consonant - without it, `A order page` and `A art gallery`
reach the output verbatim.

## Two things to know before posting

1. **No invented statistics.** Percentage hooks are the most shareable and
   the most dangerous: a made-up survey number gets you argued with in the
   comments, and a real one you did not cite gets you the same. Every number
   in here is structural - seconds, pages, steps - not a claim about a study.

2. **Not every pairing is yours.** `Put your prices on the delivery page and
   watch your driving school change` is nonsense for a driving school. The
   bank is a starting point: swap `thing` for the page you actually mean.
   The `biz` and `thing` fields are there precisely so you can re-run the
   query for your own trade.

## Regenerating

```bash
python ideas.py build           # 100,000
python ideas.py build 250000    # more, if you need them
```

Bank sizes live at the top of `bot/ideas.py` (`BIZ`, `THING`, `ANGLES`).
Add a template and rebuild; `check` tells you whether it broke anything.
