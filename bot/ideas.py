# -*- coding: utf-8 -*-
"""Build and query the content-idea bank.

    python ideas.py build                 # write ../ideas/ideas.jsonl
    python ideas.py build 250000          # a bigger bank
    python ideas.py find --angle loss --biz "dental clinic" -n 5
    python ideas.py find --contains "near me"

Every idea is one line of JSON:

    {"id":..,"hook":..,"angle":..,"format":..,"platform":..,
     "bank":..,"biz":..,"thing":..,"cta":..}

`hook` is the line that goes on screen and gets spoken; the rest is how you
find it again. Hooks are built from a hand-written template per angle, with
two slots filled from the business and website-part lists - that is what
lets100k of them exist without them being100k rewordings of one sentence.

No invented survey percentages anywhere: a hook that states a number a
reader can dispute is a hook that gets the account argued with in the
comments. Numbers that appear are structural (seconds, pages, steps).
"""
import argparse
import io
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IDEAS = os.path.join(os.path.dirname(HERE), "ideas")
DEFAULT_N = 100_000
SEED = 5913

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

# ---------------------------------------------------------------- banks --
BIZ = [
    "restaurant", "cafe", "barbershop", "dental clinic", "law firm", "gym",
    "flower shop", "boutique", "bakery", "plumbing business",
    "photography studio", "hair salon", "estate agency", "car repair shop",
    "pet groomer", "yoga studio", "tutoring service", "food truck",
    "jewellery shop", "optician", "travel agency", "daycare",
    "cleaning service", "landscaping company", "wedding planning studio",
    "music school", "coffee roastery", "bookshop", "hardware shop",
    "tailor", "nail salon", "massage clinic", "screen printing shop",
    "sign maker", "wedding photographer", "personal trainer",
    "accountancy practice", "insurance agency", "local brewery",
    "shoe repair shop", "ice cream shop", "bike repair shop",
    "veterinary clinic", "physiotherapy clinic", "electrician",
    "roofing company", "wedding venue", "escape room", "art gallery",
    "campsite", "farm shop", "car wash", "driving school",
    "language school", "print shop", "recruitment agency",
    "courier service", "sports club", "dance school", "locksmith",
]

# Everything here is a thing a customer looks at before contacting a
# business, so "the {thing} is not doing its job" reads true for all of them.
THING = [
    "website", "booking page", "Google listing", "price list",
    "photo gallery", "online menu", "contact page", "review page",
    "portfolio", "quote form", "opening-hours page", "service page",
    "product page", "testimonial page", "landing page", "one-page site",
    "mobile site", "booking calendar", "order page", "directions page",
    "homepage", "about page", "pricing page", "team page", "delivery page",
    "events page", "membership page", "gift card page", "waitlist page",
    "case study page", "local landing page", "FAQ page",
]

FORMATS = [
    "reel", "carousel", "story set", "pin", "short", "before-after post",
    "myth-busting reel", "listicle carousel", "tutorial reel",
    "opinion take", "teardown", "faq story", "poll", "day-in-the-life reel",
    "case study post", "checklist carousel", "contrast post",
    "question sticker", "quote card", "countdown", "screen recording",
    "split-screen", "text-on-video", "annotated screenshot", "reply video",
]

PLATFORMS = [
    "instagram reel", "instagram carousel", "instagram story", "tiktok",
    "pinterest pin", "youtube short",
]

CTAS = [
    "Save this for later.", "Send it to the person who needs it.",
    "Follow for more.", "Try this with your own site tonight.",
    "Comment your industry and I will take a look.",
    "Which of these is your biggest problem?",
    "Bookmark this one.", "Share it with your business partner.",
    "Do this before you spend on ads.",
    "Tell me in the comments which one you are guilty of.",
    "Check yours right now.", "Part one - more to come.",
    "Steal this.", "Read it twice.", "Send it to your web person.",
]

# ------------------------------------------------------------- angles ----
# Each list holds complete sentences with {biz} and {thing}. They are read
# as copy, so they are written to survive any substitution from the banks.
ANGLES = {
    "loss": [
        "Nobody can find your {biz} online, and the {thing} is not helping.",
        "Every day your {thing} stays vague is a day your {biz} loses work.",
        "Competitors are showing up for {biz} searches. You are not.",
        "People look for a {biz} near them tonight - will they see you?",
        "The {thing} you keep postponing is costing your {biz} customers.",
        "If your {biz} has no working {thing}, you are invisible to buyers.",
        "Your {biz} is one search away from being forgotten.",
        "A customer is choosing someone else right now because of your {thing}.",
        "A {biz} with a weak {thing} is a place with the lights off.",
        "You are not losing to a better {biz}. You are losing to a better {thing}.",
    ],
    "curiosity": [
        "The one page every {biz} needs and almost nobody builds.",
        "What your {thing} says about your {biz} before you speak.",
        "Why a plain {thing} beats a fancy one for any {biz}.",
        "The {thing} that quietly decides who gets the job.",
        "Nobody talks about this part of a {thing} for a {biz}.",
        "The five-second test every {thing} should pass.",
        "What customers check on your {thing} before they ever call.",
        "The hidden reason your {thing} looks cheap on a phone.",
        "How a {biz} with a simple {thing} outsells a bigger one.",
        "The part of your {thing} that search engines read first.",
    ],
    "proof": [
        "Most people decide about your {biz} before they ever call you.",
        "A slow {thing} loses work before anyone sees your {biz} at its best.",
        "Your {thing} is open when your {biz} is closed - what does it say?",
        "Customers read your {thing} first and your reviews second.",
        "Search engines cannot recommend a {biz} they cannot read.",
        "The cheapest advertising a {biz} ever buys is a working {thing}.",
        "Every {biz} that shows its prices gets asked fewer price questions.",
        "A phone-sized {thing} now decides most {biz} jobs.",
        "Your {thing} is the only employee that never takes a day off.",
        "People compare three {biz} websites side by side in one minute.",
    ],
    "mistake": [
        "Your {thing} has mistakes on it that are costing your {biz} jobs.",
        "You built the {thing} for your {biz}. The customer needed something else.",
        "A contact form alone is not a {thing} strategy for a {biz}.",
        "Stop redesigning your {thing}. Fix these things first.",
        "The biggest {thing} mistake a {biz} makes is hiding its prices.",
        "Your {thing} loads, but it does not sell for your {biz}.",
        "You changed the logo. The {thing} problem is still there.",
        "Nobody scrolls to the bottom of your {thing} to find your {biz}.",
        "A beautiful {thing} that nobody can find is a wasted {biz}.",
        "If your {thing} needs an explanation, your {biz} is in trouble.",
    ],
    "quickwin": [
        "Fix your {thing} this afternoon and your {biz} feels it this week.",
        "One page, one afternoon, more jobs for your {biz}.",
        "Put your prices on the {thing} and watch your {biz} change.",
        "The fastest way to make a {biz} look bigger: fix the {thing}.",
        "Ten minutes on your {thing} beats a month of posting for your {biz}.",
        "You can improve your {thing} today without hiring anyone.",
        "One afternoon on the {thing} can change the year for your {biz}.",
        "Put your phone number on the {thing} and stop losing calls.",
        "Before you spend on ads, spend an hour on the {thing}.",
        "The cheapest upgrade your {biz} can make is its {thing}.",
    ],
    "versus": [
        "Big chains win on budget. Your {biz} can win on the {thing}.",
        "Your {biz} does not need to look like a chain. It needs a working {thing}.",
        "The difference between two {biz} sites in one town is usually the {thing}.",
        "Fancy {thing} or fast {thing}? Your {biz} needs the second one.",
        "Any {thing} beats no {thing} at all for a {biz}.",
        "Your {biz} against the chain: the {thing} is where you win.",
        "Spend less on the {thing} and more on the {biz} itself.",
        "A plain {thing} that sells beats a clever one that confuses.",
        "Your {biz} can out-rank the big names with a better {thing}.",
        "Two {biz} sites, same town, same prices - the {thing} decided it.",
    ],
    "myth": [
        "Myth: a {biz} does not need a {thing}. Reality: it is losing work.",
        "You do not need a fancy {thing} to grow a {biz}.",
        "Posting on social media is not the same as having a {thing} for your {biz}.",
        "Nobody ever found a {biz} by searching for a logo.",
        "Having a {thing} is not the same as having a working one.",
        "Your free {thing} may be costing your {biz} money quietly.",
        "A {thing} is not an expense for a {biz}. It is the shop window.",
        "You do not need an app. Your {biz} needs a {thing} that works.",
        "Treating your {thing} like a brochure is how a {biz} stays invisible.",
        "More pages will not save your {thing}. Better ones will.",
    ],
    "contrarian": [
        "Your {thing} matters more than your logo, {biz} owners included.",
        "Delete half the pages on your {thing}. Your {biz} will thank you.",
        "The prettiest {thing} in town may be the hardest to read.",
        "Stop chasing followers. Fix the {thing} they land on.",
        "Your logo is the least important part of your {thing}.",
        "If the {thing} is confusing, the whole {biz} looks confusing.",
        "Ranking on Google means little if the {thing} does not sell.",
        "Most {biz} redesigns change the colours and miss the point.",
        "I would take a plain {thing} that converts over a clever one.",
        "Your {thing} should sell before it impresses anyone.",
    ],
    "howto": [
        "Five things every {biz} {thing} must have.",
        "A one-page {thing} checklist for a busy {biz}.",
        "How to build a {thing} that brings your {biz} real jobs.",
        "The three lines every {biz} {thing} should open with.",
        "How to write copy for your {thing} that customers actually read.",
        "Put these blocks on your {thing} and your {biz} starts selling.",
        "How to photograph your {biz} so the {thing} looks trustworthy.",
        "The one question to answer at the top of every {thing}.",
        "How a {biz} can turn its {thing} into a booking machine.",
        "The simple structure that works for any {biz}'s {thing}.",
    ],
    "story": [
        "This {biz} fixed its {thing} and stopped losing work to the big names.",
        "What changed for a {biz} after one honest {thing}.",
        "A {biz} owner spent one weekend on the {thing}. Then the calls came.",
        "The {biz} that almost closed, and the {thing} that turned it around.",
        "How a small {biz} outperformed a chain with a plain {thing}.",
        "Before and after: the same {biz}, a completely different {thing}.",
        "One year later: what a proper {thing} did for this {biz}.",
        "They told this {biz} a {thing} was not worth it. Watch this.",
        "The {biz} owner who finally put prices on the {thing}.",
        "From nobody found them to fully booked - same {biz}, new {thing}.",
    ],
    "question": [
        "Can a stranger tell what your {biz} does in five seconds?",
        "When did you last open your own {thing} on a phone?",
        "What would a customer pay if your {thing} showed no prices?",
        "How many jobs has your {thing} turned away this month?",
        "What appears first when someone searches your {biz} name?",
        "How long does it take to find your phone number on the {thing}?",
        "Would you buy from your own {thing} today?",
        "What does your {thing} look like on the smallest phone you own?",
        "Is your {thing} working for your {biz} or just sitting there?",
        "If your {biz} closed tomorrow, how many links would still point at you?",
    ],
    "promise": [
        "A {thing} that books jobs while your {biz} sleeps.",
        "Make your {biz} easier to choose with a clearer {thing}.",
        "Turn the {thing} into the hardest-working part of your {biz}.",
        "Get found, get chosen, get booked - fix the {thing} first.",
        "Give your {biz} a {thing} that answers every question before you do.",
        "Show the work. Show the price. Grow the {biz}.",
        "A {thing} that makes your {biz} the obvious local choice.",
        "Stop explaining. Let the {thing} sell your {biz}.",
        "Fewer calls asking if you are open, and more booked jobs for your {biz}.",
        "Your {biz} deserves a {thing} as good as the work it does.",
    ],
    "warning": [
        "If your {thing} is slow, your {biz} is paying for it silently.",
        "The {thing} is the weakest link in your {biz}.",
        "One broken form on the {thing} and your {biz} loses those leads.",
        "An outdated {thing} reads as an outdated {biz}.",
        "A {thing} nobody maintains can take a {biz} offline for days.",
        "If your {thing} is not mobile-ready, your {biz} is invisible on half the phones.",
        "The free theme nobody updates eventually costs the {biz}.",
        "Your {thing} is either bringing work in or quietly pushing it away.",
        "An unclaimed listing and a weak {thing} are a bad pair for a {biz}.",
        "Nobody warns a {biz} that a broken {thing} costs them every day.",
    ],
    "local": [
        "Everyone searches for a {biz} near me. Does your {thing} answer?",
        "Win the near-me searches in your town with a better {thing}.",
        "Your {biz} should be the first result, not the fifth.",
        "Local customers are looking now. Your {thing} should be ready.",
        "Your {biz} needs more than a pin on a map - it needs a {thing}.",
        "Show your hours, your prices and your map on the {thing}.",
        "Two streets apart, one {biz} chosen over the other because of the {thing}.",
        "A {thing} with your address and hours beats every flyer you print.",
        "Your {biz} is local. Your {thing} should say so loudly.",
        "People drive past ten {biz} options to pick the one they could read.",
    ],
    "money": [
        "The cheapest marketing your {biz} will ever buy is a working {thing}.",
        "You are paying for ads that point at a weak {thing}.",
        "A {thing} costs less than one lost customer for your {biz}.",
        "What a single missed enquiry costs a {biz} over a year.",
        "Stop renting attention. The {thing} your {biz} sends people to should be yours.",
        "Your budget goes to clicks while the {thing} waits to be fixed.",
        "One customer a week pays for the {thing} many times over.",
        "Print flyers, run ads, and still lose the job to a better {thing}.",
        "How much is the {thing} quietly costing your {biz} each month?",
        "Cheap now, expensive later: the {thing} most {biz} owners regret.",
    ],
    "urgency": [
        "Your competitor updated their {thing} while you read this.",
        "Tonight, someone searching for your {biz} will find someone else.",
        "Before the weekend: the fixes your {thing} needs.",
        "Every hour the {thing} stays wrong, the {biz} pays for it.",
        "The busy season is coming. Is the {thing} ready?",
        "Fix your {thing} before the next enquiry, not after your {biz} loses one.",
        "By this time next month the {thing} could be bringing in work.",
        "Searches for your {biz} peak tonight. Where will they land?",
        "Fix your {thing} today and your {biz} benefits all week.",
        "The first {biz} to show clear prices usually gets the call.",
    ],
    "secret": [
        "The {thing} detail your competitors hope you never notice.",
        "What the top {biz} in your town do differently with the {thing}.",
        "A small {thing} change that changes how a {biz} is judged.",
        "The quiet reason one {biz} in town gets all the calls.",
        "Nobody tells {biz} owners this about their {thing}.",
        "The {thing} habit that separates a booked-out {biz} from a quiet one.",
        "Why the third line of your {thing} matters more than the first.",
        "The {thing} section almost every {biz} owner forgets to write.",
        "What to put above the fold - the part of your {biz} {thing} people actually read.",
        "The one {thing} rule the busiest {biz} owners follow.",
    ],
    "challenge": [
        "Time how long your {thing} takes to load on a phone.",
        "Open your {thing} on your phone right now. Still readable?",
        "Find your phone number on the {thing} in under three seconds.",
        "Show your {thing} to one stranger and watch where they look.",
        "Read your {thing} out loud. Would you still call your {biz}?",
        "Scroll your {thing} once. Did the price ever appear?",
        "Ask a friend what your {biz} does, using only the {thing}.",
        "Count the taps it takes to contact your {biz} from the {thing}.",
        "Compare your {thing} with the best {biz} in town. Be brutal.",
        "Take the five-second test with your {thing} today.",
    ],
    "listicle": [
        "Three {thing} fixes every {biz} should do this week.",
        "Pages that make a {biz} website worth visiting.",
        "Four words that make any {thing} easier to read.",
        "Questions your {thing} should answer before a customer calls.",
        "Two colours, one font: the plain {thing} that works.",
        "Photos your {biz} {thing} is missing and nobody notices.",
        "Lines of copy that make a {biz} sound trustworthy.",
        "Mistakes that make a {thing} look abandoned.",
        "Places to put your phone number on a {thing}.",
        "Three seconds is all a stranger spends on your {biz} {thing}.",
    ],
    "transformation": [
        "Same {biz}, new {thing}: what actually changed.",
        "Before: invisible. After: booked. Here is what we fixed first.",
        "The before-and-after every {biz} owner should look at.",
        "One page replaced five confusing ones for this {biz}.",
        "We did not touch the logo. We fixed the {thing}.",
        "From a dead {thing} to a steady stream of {biz} enquiries.",
        "The old {thing} and the new one - spot the difference.",
        "Same prices, same town, more calls: the {thing} did it.",
        "What one afternoon on the {thing} looked like for a {biz}.",
        "The redesign that changed nothing, and the {thing} fix that worked.",
    ],
}


def templates():
    """(angle, template) pairs in a stable order."""
    for angle in sorted(ANGLES):
        for tpl in ANGLES[angle]:
            yield angle, tpl


# Words written with a vowel letter but read with a consonant sound. Getting
# these backwards is the one place an automated a/an pass goes visibly wrong.
# Note 'only', 'order', 'opening' and 'online' are NOT here: those open with
# a clear vowel sound, so they take 'an'.
_CONSONANT_O = frozenset([
    "one", "ones", "once", "union", "unique", "unit", "useful", "user",
    "users", "usual", "used",
])

# The mirror image: a consonant letter that is not pronounced.
_SILENT_H = frozenset([
    "hour", "hours", "hourly", "honest", "honestly", "honor", "honour",
    "honorary", "heir", "heirs", "herb",
])


def _vowel_sound(word):
    m = re.match(r"[A-Za-z]+", word)
    if not m:
        return False
    w = m.group(0).lower()
    if w in _SILENT_H:
        return True
    if w in _CONSONANT_O:
        return False
    return w[0] in "aeiou"


def fix_articles(text):
    """Make a / an agree with whatever the slot just substituted in.

    Templates are written with a plain 'a', because most of the bank opens
    with a consonant. Without this pass, 'A order page' and 'A art gallery'
    would reach the output verbatim - and with 100k of them, they would.
    """
    out, i = [], 0
    for m in re.finditer(r"\b(A|a)(?=\s+\S)", text):
        word = text[m.end():].lstrip().split(" ", 1)[0]
        art = m.group(1)
        if _vowel_sound(word) != (art == "an"):
            art = "An" if art.isupper() else "an"
        out.append(text[i:m.start()] + art)
        i = m.end()
    out.append(text[i:])
    return "".join(out)


def build(n=DEFAULT_N, seed=SEED):
    """n unique ideas, drawn from every valid angle x biz x thing triple.

    Deduplicated as it goes: a template missing one of the slots produces
    the same sentence for every value of that slot, and a bank whose
    "100k ideas" are 800 copies of forty sentences is worthless.
    """
    combos, seen = [], set()
    for angle, tpl in templates():
        for biz in BIZ:
            for thing in THING:
                hook = fix_articles(tpl.format(biz=biz, thing=thing))
                if hook in seen:
                    continue
                seen.add(hook)
                combos.append((angle, hook, biz, thing))

    rng = random.Random(seed)
    rng.shuffle(combos)
    if n > len(combos):
        print(f"only {len(combos)} unique hooks exist; raising n")
        n = len(combos)

    rows = []
    for i, (angle, hook, biz, thing) in enumerate(combos[:n], start=1):
        rows.append({
            "id": i,
            "hook": hook,
            "angle": angle,
            "format": FORMATS[i % len(FORMATS)],
            "platform": PLATFORMS[i % len(PLATFORMS)],
            "biz": biz,
            "thing": thing,
            "cta": CTAS[i % len(CTAS)],
        })
    return rows


def write(rows, path=IDEAS):
    os.makedirs(path, exist_ok=True)
    out = os.path.join(path, "ideas.jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    return out


def load(path=None):
    path = path or os.path.join(IDEAS, "ideas.jsonl")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def find(args):
    hits = []
    for r in load(args.path):
        if args.angle and r["angle"] != args.angle:
            continue
        if args.biz and args.biz.lower() not in r["biz"].lower():
            continue
        if args.format and r["format"] != args.format:
            continue
        if args.platform and r["platform"] != args.platform:
            continue
        if args.contains and args.contains.lower() not in r["hook"].lower():
            continue
        hits.append(r)
        if args.limit and len(hits) >= args.limit:
            break
    for r in hits:
        print(f"  [{r['id']:>6}] {r['angle']:<13} {r['format']:<18} "
              f"{r['platform']:<18} {r['hook']}")
    print(f"\n  {len(hits)} shown"
          + ("" if args.limit else "  (no --limit, stopped at the first match)")
          if args.limit else f"\n  {len(hits)} matches in total")


def wrong_article(text):
    """Describe the first a/an disagreement, or None if there is none."""
    for m in re.finditer(r"\b(A|a|An|an)(?=\s+\S)", text):
        word = text[m.end():].lstrip().split(" ", 1)[0]
        art = m.group(1)
        want = "an" if _vowel_sound(word) else "a"
        if art.lower() != want:
            return f"{art} before {word!r} (should be {want})"
    return None


def check(args):
    """Quality gate over a built bank. Run it before trusting the file.

    Catches the four ways a template bank goes wrong: a slot that did not
    fill, a hook that repeats, an a/an disagreement, and a line so long it
    would never fit on screen.
    """
    seen = set()
    n = 0
    problems = []
    for r in load(args.path):
        n += 1
        h = r["hook"]
        where = f"id {r['id']}"
        if not h.strip():
            problems.append(f"{where}: empty hook")
            continue
        if h in seen:
            problems.append(f"{where}: duplicate hook {h!r}")
        seen.add(h)
        if "{" in h or "}" in h:
            problems.append(f"{where}: unfilled slot {h!r}")
        if "  " in h or h != h.strip():
            problems.append(f"{where}: stray whitespace {h!r}")
        bad = wrong_article(h)
        if bad:
            problems.append(f"{where}: {bad}  in {h!r}")
        words = len(h.split())
        if words > args.max_words:
            problems.append(f"{where}: {words} words (> {args.max_words}) "
                            f"{h!r}")
        if args.stop and len(problems) >= args.stop:
            break

    print(f"scanned {n:,} ideas")
    print(f"  {len(seen):,} unique hooks")
    if problems:
        print(f"  FAILED: {len(problems):,} problem(s)"
              + ("" if args.stop else ""))
        for p in problems[:40]:
            print("   -", p)
        return 1
    print("  ok: every hook unique, every slot filled, a/an agreed")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="content idea bank")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write ideas.jsonl")
    b.add_argument("n", nargs="?", type=int, default=DEFAULT_N)
    b.add_argument("--path", default=IDEAS)

    f = sub.add_parser("find", help="search an existing bank")
    f.add_argument("-n", "--limit", type=int, default=8)
    f.add_argument("--path")
    f.add_argument("--angle")
    f.add_argument("--biz")
    f.add_argument("--format")
    f.add_argument("--platform")
    f.add_argument("--contains")

    c = sub.add_parser("check", help="quality gate over a built bank")
    c.add_argument("--path")
    c.add_argument("--max-words", type=int, default=20,
                   help="a hook longer than this would not fit on screen")
    c.add_argument("--stop", type=int, default=0,
                   help="stop after this many problems (0 = all)")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        rows = build(args.n)
        path = write(rows, args.path)
        size = os.path.getsize(path)
        angles = len({r["angle"] for r in rows})
        hooks = len({r["hook"] for r in rows})
        print(f"{len(rows):,} ideas -> {path}")
        print(f"  {size/1e6:.1f} MB   {hooks:,} unique hooks   "
              f"{angles} angles   {len(BIZ)} businesses   {len(THING)} parts")
        print(f"  {len(FORMATS)} formats   {len(PLATFORMS)} platforms")
        return 0
    if args.cmd == "check":
        return check(args)
    find(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
