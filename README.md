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
| 2. media | Pexels API (photos + stock video) | falls back to Pollinations (free, keyless), then to Pinterest if `PINTEREST_TOKEN` is set. |
| 3. render | Pillow (posts) / ffmpeg (reels) | posts 1080x1350 (4:5), reels 1080x1920 (9:16), 20 s, burned-in captions. |
| 4. publish | Instagram Graph API | behind a three-part safety gate. |
| 5. state | `state/seen.json` | committed back so hooks are never reused. |

## Copy: Gemini, and what happens when the quota runs out

Gemini's **free tier is 20 requests**, and a day of content is 6 of them.
Two things protect against running dry:

- **Backoff.** A 429 is retried with exponential backoff, and calls are
  spaced at least 6 s apart. After 4 straight quota errors a circuit
  breaker opens and the model is not called again that run - every failed
  call still counts against the 20, so retrying blindly only makes it worse.
- **Written fallback.** 24 hand-written hook/caption/script sets in the same
  voice take over automatically. They go through the same
  `state/seen.json` dedupe, so the account keeps posting and never repeats.

Set `GEMINI_OFF=1` to skip the model on purpose and spend nothing.

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

**e. App Review**

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
cd bot
python -m pipeline --posts=3 --reels=3      # dry run unless env says otherwise
python test_post.py 1                        # one feed image only
python test_reel.py 1                        # one reel only
```

## Scheduling

Free GitHub Actions on a **public** repo has unlimited minutes, but a
scheduled workflow is disabled automatically after 60 days without repo
activity, and each job has a 6-hour cap. Keeping the repo active (the daily
run itself counts) avoids the first; the second is not a constraint here.

## Layout

```
bot/
  config.py      environment + secrets, font/ffmpeg lookup
  textgen.py     Gemini copy, with a no-repeat guard
  images.py      Pexels / Pollinations / Pinterest sourcing
  render.py      feed images (Pillow)
  reel.py        reels (ffmpeg)
  instagram.py   Graph API publisher + safety gate
  state.py       published-hook ledger
  pipeline.py    orchestrator
.github/workflows/
  daily-content.yml   3 posts + 3 reels, schedule commented out
  test-pipeline.yml   always-dry-run smoke test
```
