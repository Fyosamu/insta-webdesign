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

## Safety gate

Nothing is ever published unless **all** of these hold:

1. `IG_ACCESS_TOKEN` and `IG_USER_ID` are set,
2. `DRY_RUN=0`,
3. `APPROVED=1`.

Otherwise the run is a dry run: it still makes the files and prints exactly
what it *would* have posted. Both scheduled workflows default to `DRY_RUN=1`.

---

## Setup

### 1. Repository secrets

`Settings -> Secrets and variables -> Actions -> New repository secret`

| secret | required | where it comes from |
| ------ | -------- | ------------------- |
| `GEMINI_KEY` | yes | [Google AI Studio](https://aistudio.google.com/apikey) |
| `PEXELS_KEY` | yes | [pexels.com/api](https://www.pexels.com/api/) - free |
| `PUBLIC_BASE` | yes to publish | your GitHub Pages URL, e.g. `https://fyosamu.github.io/insta-webdesign` |
| `IG_ACCESS_TOKEN` | yes to publish | long-lived token, see below |
| `IG_USER_ID` | yes to publish | the Instagram user id the token belongs to |
| `PINTEREST_TOKEN` | optional | Pinterest API v5 token |

### 2. Instagram (the part only you can do)

Automated publishing is only supported through Meta's official API. That
requires, once, by hand:

1. Convert the account to **Business or Creator** (Instagram app ->
   Settings -> Account -> Switch to professional account).
2. Create a **Facebook Page** and link it to that Instagram account.
3. At [developers.facebook.com](https://developers.facebook.com) create an
   app -> add the **Instagram Graph API** product.
4. Get a **long-lived access token** with `instagram_basic`,
   `instagram_content_publish`, `pages_read_engagement`.
5. Get the **Instagram user id** from
   `GET /me/accounts -> instagram_business_account`.

Then set `IG_ACCESS_TOKEN` and `IG_USER_ID` as secrets.

> Note: Meta may require **App Review** before the token can publish to a
> real account. Until then the token works in sandbox only.

### 3. Pinterest (optional)

Pinterest API v5 has no open global keyword search - the only endpoint is
`GET /search/partner/pins`, which is **beta and needs Pinterest's approval**.
Until you have it, images come from Pexels/Pollinations and the pipeline
works fine without any Pinterest token.

### 4. Make the media reachable

Meta's server must be able to `GET` the file, so `localhost` will not work.
Easiest option: enable **GitHub Pages** on this repository serving
`out/public`, and set `PUBLIC_BASE` accordingly.

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
