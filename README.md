# insta-webdesign

Automated Instagram content pipeline: **3 feed posts + 3 reels per day**,
generated on a free GitHub Actions runner and published through the
**official Meta Graph API**.

Niche: *why every business needs a website / a website is the best place to
sell products* - English copy aimed at beginners.

---

## What it does each run

| step | tool | notes |
| ---- | ---- | ----- |
| 1. copy | Gemini (`gemini-3.8-flash`) | hook, caption, hashtags, reel script. Never repeats a hook - `state/seen.json` is committed back after every run. |
| 2. media | Pexels API (photos + stock video) | falls back to Pollinations (free, keyless), then to Pinterest if `PINTEREST_TOKEN` is set. Every request gets three attempts first, so a dropped connection does not read as "no footage matched". |
| 3. render | Pillow (posts) / ffmpeg (reels) | posts 1080x1350 (4:5). Reels are 1080x1920 (9:16) with a **spoken voice-over** and word-synced subtitles, 40-55 s. |
| 4. publish | Instagram Graph API | behind a three-part safety gate. |
| 5. state | `state/seen.json` | committed back so hooks are never reused. |

## The reels: voice-over + synced subtitles

`talk.py` builds each reel from three parts, all free:

1. **footage** - up to three different Pexels clips, chained until they cover
   the narration. One clip is usually 20-30 s while the voice-over runs 45 s;
   trimming a short clip short silently stops the picture while the audio
   keeps going, and because the container duration counts the audio nothing
   looks wrong until the streams are probed separately. `make_sample.py`
   checks the video stream against the voice for exactly this reason.
2. **voice** - `edge-tts`, free and keyless. The default is
   **`en-GB-SoniaNeural`** at `-6%`, chosen from a ten-way audition
   (`bot/make_sample.py`, results in `C:\Users\USER\Desktop\insta-voices`).
   Override per run with `REEL_VOICE` / `REEL_RATE`. It is the one input
   with no second source - if the endpoint drops the stream the reel has no
   voice at all - so a dropped or empty attempt is retried three times
   before the reel is given up on.
3. **subtitles** - drawn the way the other channels draw them: white bold
   text, black outline, dark rounded plate at **70 % opacity**, bottom of
   frame, geometry ported from MoneyPrinterTurbo's `create_text_clip`
   (`font*0.4` horizontal padding, `font*0.25` interline, `font*0.4` corner
   radius, `height*0.95 - plate height`). Timing comes from edge-tts word
   boundaries, so the line changes exactly when the word is spoken.

   Two traps handled here: a plate's end time used to carry a 0.25 s floor
   that ran past the next plate's start, so six pairs were on screen at once
   and drew through each other - ends are now clamped one frame short of the
   next start. And splitting at a fixed 9-word boundary left stubs (12 words
   became 9 + 3) that got their own sub-half-second plate; sentences now
   split into equal pieces.

   And a script long enough to overrun the one-minute limit used to have
   its **tail silently chopped off**: `total` was clamped to 59 s while the
   audio was not, and because the container duration counts the audio, every
   other check reported a healthy file. A 308-word script measured 99.7 s,
   so 40.7 s of it simply vanished - visible only by listening to the
   ending. `talk._fit()` now measures the rate for the chosen voice, drops
   back to the last **full sentence** that fits inside `MAX_SECONDS - 0.6`
   (the `0.6` is the pad, which would re-clip otherwise) and reads it again.
   It refuses rather than guessing when there is no sentence boundary.

If edge-tts or the network is down, `pipeline.make_reel` falls back to the
original silent card reel (`reel.py`) so the account still posts. GitHub
Actions is Ubuntu, so `talk.py` picks DejaVu/Liberation Bold there and
Arial/YaHei Bold on Windows.

## Copy: Gemini, and what happens when the quota runs out

Gemini's **free tier is 20 requests per day**, and it was measured as not
recovering within 9 minutes of waiting - so it behaves like a daily budget,
not a per-minute one. Three things keep the account fed:

- **One call a day.** `batch_copy()` asks for every post and reel in a
  single request instead of six. A whole day of content costs 1 of the 20,
  leaving the rest for retries and for anything else using the key.
- **Backoff, then a circuit breaker.** A 429 is retried with exponential
  backoff, calls are spaced at least 6 s apart, and after 4 straight quota
  errors the model is not called again that run. Every failed call still
  counts against the 20, so retrying blindly only makes it worse.
- **Written fallback.** 24 hand-written hook/caption/script sets in the same
  voice take over - automatically, or on purpose with `GEMINI_OFF=1`. A
  partial or duplicate-heavy answer from the model is topped up from the
  same pool. Everything goes through the `state/seen.json` dedupe, so the
  account keeps posting and never repeats.

## The three jobs, and why they are in that order

Meta's server has to be able to `GET` a media file *before* the publish
container is created, and an Actions artifact is not reachable from outside.
So `daily-content` runs:

1. **`build`** - renders everything, uploads it as an artifact, commits state.
2. **`pages`** - deploys `out/public` to GitHub Pages so the files get a
   real `https://` URL. Only runs when `publish=yes`.
3. **`publish`** - waits until Pages actually answers `200`, then hands the
   URLs to the Graph API and records what went out.

Skipped entirely when `publish` is anything other than `yes`.

Two details worth knowing:

- **Each day gets an `index.html`** (`pipeline._index()`). The wait step
  probes `$BASE/$DAY/`, a directory URL, and GitHub Pages answers `404` for
  a directory with no index - without it the first real publish run would
  have retried for five minutes and then failed while the media sat there
  perfectly fine. It also makes a deployed day browsable.
- **Pages holds only the current day.** `deploy-pages` replaces the whole
  site each run, so yesterday's directory is gone once today's deploys.
  That is fine for publishing (Meta fetches inside the same run, while the
  files are live) but it is not an archive - keep the artifacts if you want
  to look back.

## Safety gate

Nothing is ever published unless **all** of these hold:

1. `IG_ACCESS_TOKEN` and `IG_USER_ID` are set,
2. `DRY_RUN=0`,
3. `APPROVED=1`.

Otherwise the run is a dry run: it still makes the files and prints exactly
what it *would* have posted. Both scheduled workflows default to `DRY_RUN=1`.

`--render-only` skips the publish half altogether - that is what the build
job uses, so a render can never touch Instagram by accident.

---

## Setup

### 1. Repository secrets

`Settings -> Secrets and variables -> Actions -> New repository secret`

| secret | status | where it comes from |
| ------ | ------ | ------------------- |
| `GEMINI_KEY` | **set** | [Google AI Studio](https://aistudio.google.com/apikey) |
| `PEXELS_KEY` | **set** | [pexels.com/api](https://www.pexels.com/api/) - free |
| `PUBLIC_BASE` | **set** | `https://fyosamu.github.io/insta-webdesign` |
| `IG_ACCESS_TOKEN` | **you must add** | long-lived token, step 2 below |
| `IG_USER_ID` | **you must add** | the Instagram user id, step 2 below |
| `PINTEREST_TOKEN` | optional, not needed | Pinterest API v5 token |

### 2. Instagram (the part only you can do)

Automated publishing is only supported through Meta's official API. It is a
one-time setup, but it has to be done by a human with the account in front
of them - nothing in this repo can create the credentials for you.

**a. Prepare the account** (Instagram app on the phone)

1. Settings -> Account -> **Switch to professional account** -> Business.
2. Create a **Facebook Page** (any page works) and link it to this IG
   account: Settings -> Account -> **Share to other apps** -> Facebook.

**b. Create the app** (browser, ~10 min)

1. <https://developers.facebook.com/apps> -> **Create App** -> type
   *Business* -> give it any name -> Create.
2. In the dashboard add the products **Instagram Graph API** and
   **Facebook Login**.
3. Under *Instagram Graph API -> API setup with Instagram login* click
   **Add account** and log in as `akhob59`.
4. In the left sidebar open **Graph API Explorer**
   (<https://developers.facebook.com/tools/explorer>), pick your new app,
   and add these permissions: `instagram_basic`,
   `instagram_content_publish`, `pages_read_engagement`,
   `pages_show_list`.
5. **Generate access token.** This is a short-lived one (about 1 hour).

**c. Turn it into a long-lived token**

```bash
curl "https://graph.facebook.com/v21.0/oauth/access_token?\
grant_type=fb_exchange_token&client_id=APP_ID&\
client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN"
```

`APP_ID` / `APP_SECRET` are on the app's *Settings -> Basic* page. The
resulting token lasts ~60 days.

**d. Get the two values the pipeline needs**

```bash
# IG user id
curl "https://graph.facebook.com/v21.0/me/accounts?\
access_token=LONG_TOKEN"
# -> take the page id, then:
curl "https://graph.facebook.com/v21.0/PAGE_ID?\
fields=instagram_business_account&access_token=LONG_TOKEN"
```

Set the result as `IG_USER_ID`, and the long token as `IG_ACCESS_TOKEN`.

**e. Verify both, before anything is allowed to publish**

```bash
cd bot
python instagram.py check
```

Read-only — it prints the gate, reads the account back and spends no post.
It exits non-zero when `account_type` is not `BUSINESS` or `CREATOR`, which
matters: otherwise a personal account is accepted here and only refused
later at container creation, with an error that never mentions the account
type. Run this the moment the two values exist, and again after every token
renewal.

**f. App Review**

To publish to a real account (not just a test user) Meta usually requires
**App Review**, where you record a short screen-capture of the flow. This is
the step that takes days to weeks, and only Meta approves it. Until then the
token works for test users only.

> The token expires after ~60 days. Re-run step (c) before then, or the
> `publish` job will start failing with an expired-token error.

### 3. Pinterest (optional)

Pinterest API v5 has no open global keyword search - the only endpoint is
`GET /search/partner/pins`, which is **beta and needs Pinterest's approval**.
Until you have it, images come from Pexels/Pollinations and the pipeline
works fine without any Pinterest token.

### 4. Make the media reachable

Meta's server must be able to `GET` the file, so `localhost` will not work.

**Already done for this repo:** GitHub Pages is enabled with
`build_type: workflow`, and `PUBLIC_BASE` is set to
`https://fyosamu.github.io/insta-webdesign`. The `pages` job deploys
`out/public` there before every publish.

The first time the `pages` job runs, GitHub may ask you to accept the
Pages terms on the repo's Settings -> Pages page.

---

## Running

- **`test-pipeline`** workflow - always a dry run, 1 post + 1 reel. Start here.
- **`daily-content`** workflow - manual button first; the `schedule:` block is
  commented out on purpose. Set the `publish` input to `yes` to open the gate.

Locally:

```bash
pip install -r requirements.txt    # Pillow + edge-tts (ffmpeg on PATH)
cd bot
python -m pipeline --posts=3 --reels=3      # dry run unless env says otherwise
python test_post.py 1                        # one feed image only
python test_reel.py 1                        # one silent card reel (fallback path)
python make_sample.py                        # one voice reel to review
python verify_sample.py <folder>             # gate it: overlap, rows, loudness, ink
```

`make_sample.py` also writes `captions.srt` beside the video — the subtitles
are painted into the pixels, so those timings are the only way to prove
afterwards that no two plates shared a moment on screen.

Those timings only prove the plates were *scheduled*, though, so the gate
samples the video itself as well: frames taken from the body are looked at
for the pure-white subtitle type, and frames from the opening for the gold
of the hook chip. The test is deliberately one-sided. A low pixel count is
strong evidence that nothing was drawn, a high count only weak evidence
that something was — bright footage can look like type. So a failure here
is a real missing overlay, while a pass means the ink was there and not
that the frame could not have been pale.

## Scheduling

Free GitHub Actions on a **public** repo has unlimited minutes, but a
scheduled workflow is disabled automatically after 60 days without repo
activity, and each job has a 6-hour cap. Keeping the repo active (the daily
run itself counts) avoids the first; the second is not a constraint here.

## Layout

```
bot/
  config.py        environment + secrets, font/ffmpeg lookup
  textgen.py       Gemini copy, with a no-repeat guard
  images.py        Pexels / Pollinations / Pinterest sourcing
  render.py        feed images (Pillow)
  talk.py          voice reels: edge-tts + word-synced subtitles (ffmpeg)
  reel.py          silent card reels - the fallback path
  instagram.py     Graph API publisher + safety gate
  state.py         published-hook ledger
  pipeline.py      orchestrator
  ideas.py         the 100,000-hook content bank: build / find / check
  make_sample.py   build one sample reel for review
  test_talk.py     guards the subtitle timing invariants (offline)
  test_publish.py  walks container -> poll -> publish against a mock Graph API
  test_images.py   the transport retry, and the two ways a fetch can fail
  verify_sample.py gate a finished sample: overlap, rows, loudness, codec,
                     and whether the type is on the frame at all
.github/workflows/
  daily-content.yml   3 posts + 3 reels, schedule commented out
  test-pipeline.yml   always-dry-run smoke test
```
