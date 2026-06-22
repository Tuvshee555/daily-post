#!/usr/bin/env python3
"""
Sello AI — social media auto-poster (AI-generated content).

On each run it:
  1. Refreshes the FB token (long-lived exchange).
  2. Picks a fresh content angle (rotating, never the same as last run).
  3. Asks DeepSeek to write the hook + caption + image prompt in
     Mongolian Cyrillic (no hardcoded templates — fresh every run).
  4. Generates a 1024x1024 image with Stability AI from the AI image prompt,
     then overlays the Mongolian hook + brand with Pillow (Stability can't
     render Cyrillic text reliably, so the headline is composited on top).
  5. Commits the image to this GitHub repo and uses its public raw URL.
  6. Posts the photo to the Facebook Page.
  7. Posts the photo to Instagram (create container -> publish).
  8. Logs exactly what happened.

Designed to run from GitHub Actions. All credentials come from env vars.
"""

import base64
import io
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone

import requests
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------- #
# Hardcoded account IDs
# --------------------------------------------------------------------------- #
FACEBOOK_PAGE_ID = "1079728475218630"
INSTAGRAM_ACCOUNT_ID = "17841442639401188"

GRAPH_VERSION = "v19.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

# --------------------------------------------------------------------------- #
# Secrets (from environment)
# --------------------------------------------------------------------------- #
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
FB_APP_ID = os.environ.get("FB_APP_ID", "").strip()
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "").strip()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
STABILITY_API_KEY = os.environ.get("STABILITY_API_KEY", "").strip()


# --------------------------------------------------------------------------- #
# AI content generation (DeepSeek)
# --------------------------------------------------------------------------- #
ANGLES = [
    "Late night missed messages",
    "Lost customer to competitor",
    "Specific shop type: clothing",
    "Specific shop type: shoes",
    "Specific shop type: auto parts",
    "Specific shop type: cosmetics",
    "Specific shop type: food",
    "Specific shop type: electronics",
    "Specific shop type: furniture",
    "Free tier / low risk offer",
    "Before vs after using AI bot",
    "Cost of slow replies",
    "Competitor already using AI",
    "Demo / what customer sees",
    "Time saved per week",
    "Money lost from no reply",
]

SYSTEM_PROMPT = """
You are a social media content creator for Sello AI — an AI sales chatbot
for Mongolian online shops. You only write in Mongolian (Cyrillic).

Business context:
- Sello AI answers Facebook Messenger and Instagram DM messages automatically 24/7
- Target customers: Mongolian online shop owners (clothing, shoes, auto parts,
  cosmetics, electronics, furniture, food)
- Pricing: Үнэгүй (0₮, 25 users), Стартер (49,000₮, 250 users),
  Өсөлт (69,000₮, 800 users - most popular), Бизнес (99,000₮, 2500 users)
- 14 day free trial available
- Contact: +976 8618 5769
- CTA always: "БОТ" гэж мессеж бичээрэй 👇
- Brand: deep blue #2563EB, clean modern SaaS style

Post structure always: Pain → Solution → Result → CTA
Keep captions short, punchy, emotional. Use emojis. Line breaks between points.
Hashtags in Mongolian: #SelloAI #ОнлайнДэлгүүр #AIБот #ЦахимХудалдаа #ЖижигБизнес
""".strip()


def _read_last_angle():
    try:
        with open("last_angle.txt", "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, IOError):
        return ""


def _write_last_angle(angle):
    try:
        with open("last_angle.txt", "w", encoding="utf-8") as fh:
            fh.write(angle)
    except (OSError, IOError) as exc:
        print(f"⚠️  Could not write last_angle.txt: {exc}")


def pick_angle():
    """Pick a random angle, avoiding the one used last run."""
    last = _read_last_angle()
    choices = [a for a in ANGLES if a != last] or ANGLES
    angle = random.choice(choices)
    _write_last_angle(angle)
    return angle


def generate_content(angle):
    """Ask DeepSeek for hook + caption + image_prompt as JSON (Mongolian)."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is missing.")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    user_prompt = (
        f'Use this angle for the post: "{angle}".\n\n'
        "Write:\n"
        "1. hook: short headline for image (in Mongolian, max 8 words)\n"
        "2. caption: full post caption with emojis and hashtags\n"
        "3. image_prompt: English description for image generation using this style: "
        '"Clean modern flat illustration, white background, deep blue #2563EB accent '
        'only, square 1:1, Mongolian character style, premium SaaS marketing look, '
        'no watermark, [specific scene]"\n\n'
        'Return as JSON: {"hook": "...", "caption": "...", "image_prompt": "..."}'
    )

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=1.1,
    )
    raw = resp.choices[0].message.content
    data = json.loads(raw)

    hook = (data.get("hook") or "").strip()
    caption = (data.get("caption") or "").strip()
    image_prompt = (data.get("image_prompt") or "").strip()
    if not (hook and caption and image_prompt):
        raise RuntimeError(f"DeepSeek returned incomplete content: {data}")

    return hook, caption, image_prompt


# --------------------------------------------------------------------------- #
# Image generation (Stability AI) + Mongolian hook overlay
# --------------------------------------------------------------------------- #
SIZE = 1024
BRAND = "Sello AI"
ACCENT = (37, 99, 235)  # #2563EB deep blue


def generate_image(image_prompt):
    """Generate a 1024x1024 image with Stability AI and return PNG bytes."""
    if not STABILITY_API_KEY:
        raise RuntimeError("STABILITY_API_KEY is missing.")

    resp = requests.post(
        "https://api.stability.ai/v1/generation/"
        "stable-diffusion-xl-1024-v1-0/text-to-image",
        headers={
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "text_prompts": [{"text": image_prompt, "weight": 1}],
            "cfg_scale": 7,
            "height": 1024,
            "width": 1024,
            "samples": 1,
            "steps": 30,
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Stability API failed ({resp.status_code}): {resp.text}")

    artifacts = resp.json().get("artifacts", [])
    if not artifacts:
        raise RuntimeError(f"Stability API returned no artifacts: {resp.text}")

    return base64.b64decode(artifacts[0]["base64"])


def _load_font(size, bold=True):
    """Load a TrueType font with Cyrillic support, trying common paths."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    """Greedy word-wrap to fit max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        w = draw.textbbox((0, 0), trial, font=font)[2]
        if w <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F]+",
    flags=re.UNICODE,
)


def _strip_emoji(text):
    """Remove emoji/symbols the headline font can't render (caption keeps them)."""
    return _EMOJI_RE.sub("", text).strip()


def compose_image(base_png, hook):
    """Overlay the Mongolian hook + brand bar onto the AI-generated image."""
    hook = _strip_emoji(hook)
    img = Image.open(io.BytesIO(base_png)).convert("RGB")
    if img.size != (SIZE, SIZE):
        img = img.resize((SIZE, SIZE))
    draw = ImageDraw.Draw(img, "RGBA")

    margin = 70
    max_width = SIZE - 2 * margin

    # Pick a headline font size that fits in the lower band.
    font_size = 76
    while font_size >= 42:
        font = _load_font(font_size, bold=True)
        lines = _wrap_text(draw, hook, font, max_width)
        line_h = draw.textbbox((0, 0), "Аг", font=font)[3] + 16
        total_h = line_h * len(lines)
        if len(lines) <= 4 and total_h <= SIZE * 0.32:
            break
        font_size -= 6

    brand_font = _load_font(40, bold=True)
    brand_h = draw.textbbox((0, 0), BRAND, font=brand_font)[3]

    # Dark band across the bottom for guaranteed text legibility.
    band_h = total_h + brand_h + margin + 80
    band_top = SIZE - band_h
    draw.rectangle([0, band_top, SIZE, SIZE], fill=(8, 12, 30, 200))

    # Accent bar above the headline.
    accent_y = band_top + 40
    draw.rounded_rectangle(
        [margin, accent_y, margin + 110, accent_y + 12],
        radius=6, fill=ACCENT,
    )

    # Headline text.
    y = accent_y + 36
    for line in lines:
        draw.text((margin, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    # Brand dot + name at the very bottom.
    dot_r = 12
    brand_y = SIZE - margin - brand_h
    draw.ellipse(
        [margin, brand_y + 4, margin + 2 * dot_r, brand_y + 4 + 2 * dot_r],
        fill=ACCENT,
    )
    draw.text((margin + 2 * dot_r + 18, brand_y), BRAND,
              font=brand_font, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Token refresh
# --------------------------------------------------------------------------- #
def refresh_token():
    """Exchange the page token for a fresh long-lived token.

    Falls back to the original token if the exchange fails for any reason
    (so a temporary hiccup doesn't kill the whole run).
    """
    if not (FB_APP_ID and FB_APP_SECRET and FB_PAGE_ACCESS_TOKEN):
        print("⚠️  Missing FB app creds — using the provided page token as-is.")
        return FB_PAGE_ACCESS_TOKEN

    try:
        resp = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": FB_APP_ID,
                "client_secret": FB_APP_SECRET,
                "fb_exchange_token": FB_PAGE_ACCESS_TOKEN,
            },
            timeout=30,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("access_token"):
            print("🔑 Token refreshed successfully.")
            return data["access_token"]
        print(f"⚠️  Token refresh failed ({resp.status_code}): {data}. "
              "Falling back to original token.")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Token refresh error: {exc}. Falling back to original token.")

    return FB_PAGE_ACCESS_TOKEN


def get_page_token(user_token, page_id):
    """Exchange a user token for the Page Access Token of `page_id`.

    The Page token is what's required to publish photos to the Page and to
    use the Page-linked Instagram account.

    Falls back to the provided token if the page isn't found in /me/accounts
    (e.g. the secret already holds a Page token, so /me/accounts is empty) —
    that way the run works regardless of which token type was stored.
    """
    try:
        resp = requests.get(
            f"{GRAPH}/me/accounts",
            params={"access_token": user_token},
            timeout=30,
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  /me/accounts request failed: {exc}. "
              "Using the provided token as-is.")
        return user_token

    for page in data.get("data", []):
        if page.get("id") == page_id:
            print(f"🔑 Got Page Access Token for page {page_id}.")
            return page["access_token"]

    print(f"⚠️  Page {page_id} not found in /me/accounts ({data}). "
          "Assuming the provided token is already a Page token and using it as-is.")
    return user_token


# --------------------------------------------------------------------------- #
# Image hosting (commit to this GitHub repo via the Contents API)
# Uses the automatic GITHUB_TOKEN in Actions — no extra secret needed.
# NOTE: the repo must be PUBLIC for Facebook/Instagram to fetch the raw URL,
# and the workflow needs `permissions: contents: write`.
# --------------------------------------------------------------------------- #
def upload_image(image_bytes):
    """Commit the image to the repo and return its public raw URL."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()  # e.g. "Tuvshee555/daily-post"
    if not (token and repo):
        raise RuntimeError(
            "GITHUB_TOKEN / GITHUB_REPOSITORY not set "
            "(both are provided automatically inside GitHub Actions)."
        )

    content_b64 = base64.b64encode(image_bytes).decode()
    filename = f"images/post_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
    url = f"https://api.github.com/repos/{repo}/contents/{filename}"

    resp = requests.put(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"message": f"Add post image {filename}", "content": content_b64},
        timeout=60,
    )
    if resp.status_code in (200, 201):
        raw_url = resp.json()["content"]["download_url"]
        print(f"🖼️  Committed image to GitHub: {raw_url}")
        return raw_url
    raise RuntimeError(f"GitHub upload failed ({resp.status_code}): {resp.text}")


# --------------------------------------------------------------------------- #
# Facebook + Instagram posting
# --------------------------------------------------------------------------- #
def post_to_facebook(token, image_url, message):
    """Post a photo to the Facebook Page."""
    resp = requests.post(
        f"{GRAPH}/{FACEBOOK_PAGE_ID}/photos",
        data={"url": image_url, "message": message, "access_token": token},
        timeout=60,
    )
    data = resp.json()
    if resp.status_code == 200 and (data.get("post_id") or data.get("id")):
        post_id = data.get("post_id") or data.get("id")
        print(f"✅ Facebook posted. id={post_id}")
        return True
    print(f"❌ Facebook post failed ({resp.status_code}): {data}")
    return False


def post_to_instagram(token, image_url, caption):
    """Create an IG media container then publish it."""
    # 1) Create container.
    resp = requests.post(
        f"{GRAPH}/{INSTAGRAM_ACCOUNT_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=60,
    )
    data = resp.json()
    if resp.status_code != 200 or not data.get("id"):
        print(f"❌ Instagram container creation failed ({resp.status_code}): {data}")
        return False
    creation_id = data["id"]
    print(f"📦 Instagram container created. creation_id={creation_id}")

    # Give Instagram time to fetch & process the image before publishing.
    print("⏳ Waiting for Instagram to process image...")
    time.sleep(20)

    # 2) Publish.
    resp = requests.post(
        f"{GRAPH}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=60,
    )
    data = resp.json()
    if resp.status_code == 200 and data.get("id"):
        print(f"✅ Instagram published. id={data['id']}")
        return True
    print(f"❌ Instagram publish failed ({resp.status_code}): {data}")
    return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    print("=" * 64)
    print(f"Sello AI auto-poster — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 64)

    if not FB_PAGE_ACCESS_TOKEN:
        print("❌ FB_PAGE_ACCESS_TOKEN is missing. Aborting.")
        sys.exit(1)

    # 1) Pick angle + generate fresh content with DeepSeek.
    angle = pick_angle()
    print(f"🎯 Angle: {angle}")
    try:
        hook, caption, image_prompt = generate_content(angle)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Content generation failed: {exc}")
        sys.exit(1)
    print(f"📝 Hook: {hook}")
    print(f"🖌️  Image prompt: {image_prompt}")

    # 2) Refresh token, then derive the Page Access Token used for all posts.
    token = refresh_token()
    try:
        page_token = get_page_token(token, FACEBOOK_PAGE_ID)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Could not get Page Access Token: {exc}")
        sys.exit(1)

    # 3) Generate image with Stability AI, then overlay the Mongolian hook.
    try:
        base_png = generate_image(image_prompt)
        image_bytes = compose_image(base_png, hook)
        print(f"🎨 Image generated ({len(image_bytes)} bytes).")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Image generation failed: {exc}")
        sys.exit(1)

    # 4) Host the image (commit to the repo, get a public raw URL).
    try:
        image_url = upload_image(image_bytes)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}")
        sys.exit(1)

    # 5) Post to Facebook + Instagram using the Page Access Token.
    fb_ok = post_to_facebook(page_token, image_url, caption)
    ig_ok = post_to_instagram(page_token, image_url, caption)

    # 6) Summary.
    print("-" * 64)
    print("SUMMARY")
    print(f"  Angle    : {angle}")
    print(f"  Hook     : {hook}")
    print(f"  Image    : {image_url}")
    print(f"  Facebook : {'OK ✅' if fb_ok else 'FAILED ❌'}")
    print(f"  Instagram: {'OK ✅' if ig_ok else 'FAILED ❌'}")
    print("=" * 64)

    # Exit non-zero only if BOTH failed, so one platform hiccup doesn't
    # mark the whole run red.
    if not fb_ok and not ig_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
