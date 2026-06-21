# daily-post

Automated social media posting for **Nexon Shop AI** — runs on GitHub Actions
3× daily and publishes a branded image + caption to Facebook and Instagram.

## What it does

On each run, `post.py`:

1. Refreshes the Facebook page token (long-lived exchange).
2. Picks a content template via a weekday × time-slot rotation (21 templates =
   7 days × 3 daily runs), so it never repeats the same post twice in a row and
   each week is different.
3. Renders a 1080×1080 branded image with Pillow (navy→purple gradient + headline).
4. Commits the image to this repo (`images/`) via the GitHub API and uses its
   public raw URL — uses the automatic `GITHUB_TOKEN`, no extra secret needed.
5. Posts the photo to the Facebook Page.
6. Posts the photo to Instagram (create container → publish).
7. Logs exactly what was posted and whether it succeeded.

## Setup

1. Add these **repository secrets** (Settings → Secrets and variables → Actions):
   - `FB_PAGE_ACCESS_TOKEN`
   - `FB_APP_ID`
   - `FB_APP_SECRET`

   (Image hosting commits to this repo via the automatic `GITHUB_TOKEN` — no
   extra secret. The repo must be **public** so Facebook/Instagram can fetch the
   raw image URL.)
2. The Facebook token must be a **Page token** with `pages_manage_posts` and
   `instagram_content_publish`, and the Instagram account must be a
   Business/Creator account linked to the Page.

## Schedule

Runs at **9am, 1pm, 6pm UTC** daily (`cron: "0 9,13,18 * * *"`).
You can also trigger it manually from the **Actions** tab (workflow_dispatch).

## Local test

```bash
pip install -r requirements.txt
# set the 4 env vars, then:
python post.py
```
