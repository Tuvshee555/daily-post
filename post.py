#!/usr/bin/env python3
"""
Sello AI — social media auto-poster (AI-generated, high-end design).

On each run it:
  1. Refreshes the FB token (long-lived exchange).
  2. Picks a fresh content angle (rotating, never the same as last run).
  3. Asks DeepSeek to write structured copy in Mongolian Cyrillic — headline,
     subhead, CTA, full caption, and a textless image scene (fresh every run,
     no hardcoded templates).
  4. Generates a clean, TEXTLESS premium illustration with Stability AI
     (v2beta), then composites a real designed poster on top with Pillow:
     full-bleed hero + white card, Montserrat headline/subhead, blue CTA pill,
     brand lockup and contact. Text is always crisp + correctly Mongolian.
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

# Contact shown on the poster.
CONTACT_PHONE = "+976 8618 5769"

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
You are a senior social media creative director for Sello AI — an AI sales
chatbot for Mongolian online shops. You write ONLY in flawless, natural
Mongolian (Cyrillic). Never use English in the output copy.

Business context:
- Sello AI answers Facebook Messenger and Instagram DM messages automatically 24/7
- Target customers: Mongolian online shop owners (clothing, shoes, auto parts,
  cosmetics, electronics, furniture, food)
- Pricing: Үнэгүй (0₮, 25 users), Стартер (49,000₮, 250 users),
  Өсөлт (69,000₮, 800 users - most popular), Бизнес (99,000₮, 2500 users)
- 14 day free trial available
- Contact: +976 8618 5769
- CTA always: "БОТ" гэж мессеж бичээрэй 👇
- Brand: deep blue #2563EB, clean modern premium SaaS style

Voice: confident, premium, warm, concrete. Short punchy sentences. No fluff,
no clichés, no ALL CAPS shouting. Speak directly to a busy shop owner.

Post structure always: Pain → Solution → Result → CTA.
Hashtags in Mongolian: #SelloAI #ОнлайнДэлгүүр #AIБот #ЦахимХудалдаа #ЖижигБизнес
Every hashtag must be ONE word with NO spaces inside it (write #ГооСайхан,
never #Гоо сайхан). You may add one relevant single-word hashtag for the shop type.
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


def _fix_hashtag_lines(caption):
    """Repair hashtags broken across a space (#Гоо сайхан -> #Гоосайхан).

    Only touches lines that begin with '#', so caption prose is untouched.
    """
    out = []
    for line in caption.split("\n"):
        if line.strip().startswith("#"):
            merged = []
            for tok in line.split():
                if tok.startswith("#") or not merged:
                    merged.append(tok)
                else:  # a stray word that belongs to the previous hashtag
                    merged[-1] += tok
            out.append(" ".join(merged))
        else:
            out.append(line)
    return "\n".join(out)


def generate_content(angle):
    """Ask DeepSeek for structured Mongolian copy + a textless image scene."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is missing.")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    user_prompt = (
        f'Create one premium social post for this angle: "{angle}".\n\n'
        "Return JSON with these fields (all copy in Mongolian Cyrillic, no English):\n"
        '- "headline": the poster headline. Bold, emotional, max 6 words. NO emojis.\n'
        '- "subhead": one supporting benefit line for the poster, max 10 words. '
        "NO emojis.\n"
        '- "cta": short button text for the poster, max 4 words (e.g. '
        '\'"БОТ" гэж бичээрэй\'). NO emojis.\n'
        '- "caption": the full post caption. Pain → Solution → Result → CTA, '
        "with emojis, line breaks between points, end with the CTA "
        '\'"БОТ" гэж мессеж бичээрэй 👇\' and then the Mongolian hashtags.\n'
        '- "image_scene": an ENGLISH description of ONLY the visual subject/scene '
        "for an illustration (e.g. 'a happy Mongolian shoe shop owner checking "
        "phone notifications, stylized shoes on shelves, a friendly chat bubble'). "
        "Describe subject and action only. NO text, NO letters, NO words, NO logos, "
        "NO style words — just the scene.\n\n"
        'Output ONLY valid JSON: {"headline": "...", "subhead": "...", '
        '"cta": "...", "caption": "...", "image_scene": "..."}'
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
    data = json.loads(resp.choices[0].message.content)

    content = {
        "headline": (data.get("headline") or "").strip(),
        "subhead": (data.get("subhead") or "").strip(),
        "cta": (data.get("cta") or "").strip() or '"БОТ" гэж бичээрэй',
        "caption": _fix_hashtag_lines((data.get("caption") or "").strip()),
        "image_scene": (data.get("image_scene") or "").strip(),
    }
    if not (content["headline"] and content["caption"] and content["image_scene"]):
        raise RuntimeError(f"DeepSeek returned incomplete content: {data}")

    return content


# --------------------------------------------------------------------------- #
# Image generation (Stability AI v2beta) — clean, TEXTLESS hero illustration
# --------------------------------------------------------------------------- #
SIZE = 1080

# Fixed art direction appended to every scene so all posts share one premium,
# consistent brand look.
STYLE_SUFFIX = (
    "clean modern flat vector illustration, premium SaaS marketing style, "
    "deep blue (#2563EB) and white color palette with soft sky-blue accents, "
    "lots of negative space, soft studio lighting, subtle long shadows, "
    "rounded geometric shapes, friendly and professional, elegant, minimal, "
    "high-end, crisp, highly detailed, centered balanced composition"
)
NEGATIVE_PROMPT = (
    "text, letters, words, numbers, captions, typography, watermark, logo, "
    "signature, ui mockup, buttons, frame, border, low quality, blurry, jpeg "
    "artifacts, deformed, distorted, cluttered, busy background, extra fingers, "
    "ugly, messy, oversaturated"
)


def generate_image(scene):
    """Generate a clean textless 1:1 illustration and return PNG bytes."""
    if not STABILITY_API_KEY:
        raise RuntimeError("STABILITY_API_KEY is missing.")

    # Default to "core" (~3 credits/image ≈ $0.03) — premium quality at a
    # fraction of Ultra's cost. Override with STABILITY_MODEL=ultra|sd3.5 if needed.
    model = os.environ.get("STABILITY_MODEL", "core").lower()
    endpoint = {"ultra": "ultra", "core": "core", "sd3.5": "sd3", "sd3": "sd3"}.get(
        model, "core"
    )
    url = f"https://api.stability.ai/v2beta/stable-image/generate/{endpoint}"

    prompt = f"{scene}. {STYLE_SUFFIX}"
    data = {
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "aspect_ratio": "1:1",
        "output_format": "png",
    }
    if endpoint == "sd3":
        data["model"] = "sd3.5-large"
    if endpoint == "core":
        data["style_preset"] = "digital-art"

    resp = requests.post(
        url,
        headers={
            "authorization": f"Bearer {STABILITY_API_KEY}",
            "accept": "image/*",
        },
        files={"none": ""},  # forces multipart/form-data
        data=data,
        timeout=180,
    )
    if resp.status_code == 200:
        return resp.content
    raise RuntimeError(f"Stability API failed ({resp.status_code}): {resp.text[:500]}")


# --------------------------------------------------------------------------- #
# Typography (Montserrat — full Cyrillic — fetched + cached once)
# --------------------------------------------------------------------------- #
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/"
    "Montserrat%5Bwght%5D.ttf"
)
FONT_PATH = "fonts/Montserrat.ttf"


def _font_path():
    """Download + cache the Montserrat variable font, return its local path."""
    if not os.path.exists(FONT_PATH):
        os.makedirs("fonts", exist_ok=True)
        resp = requests.get(FONT_URL, timeout=60)
        resp.raise_for_status()
        with open(FONT_PATH, "wb") as fh:
            fh.write(resp.content)
    return FONT_PATH


def _font(size, weight=700):
    """Load Montserrat at a given size + weight (100-900)."""
    font = ImageFont.truetype(_font_path(), size)
    try:
        font.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001 — static fallback if variable axes unsupported
        pass
    return font


# --------------------------------------------------------------------------- #
# Poster composition
# --------------------------------------------------------------------------- #
BRAND = "Sello AI"
NAVY = (15, 23, 42)        # #0F172A
GRAY = (71, 85, 105)       # #475569
BLUE = (37, 99, 235)       # #2563EB
LIGHT_BLUE = (219, 234, 254)  # #DBEAFE
WHITE = (255, 255, 255)

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F]+",
    flags=re.UNICODE,
)


def _clean(text):
    """Strip emoji/symbols the font can't render, collapse whitespace."""
    return re.sub(r"\s+", " ", _EMOJI_RE.sub("", text)).strip()


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap to fit max_width."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _cover(img, w, h):
    """Resize+crop an image to exactly fill w x h (object-fit: cover)."""
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _text_h(draw, font):
    return draw.textbbox((0, 0), "Аг", font=font)[3]


def compose_poster(base_png, headline, subhead, cta):
    """Composite a premium poster: hero image + white card with crisp copy."""
    headline = _clean(headline)
    subhead = _clean(subhead)
    cta = _clean(cta)

    canvas = Image.new("RGB", (SIZE, SIZE), WHITE)

    # --- Hero illustration fills the top, full-bleed. --------------------- #
    hero_h = 648
    hero = _cover(Image.open(io.BytesIO(base_png)).convert("RGB"), SIZE, hero_h)
    canvas.paste(hero, (0, 0))

    # --- White card with a rounded top lip overlapping the hero. ---------- #
    card_top = hero_h - 36
    # Soft shadow above the card lip for lift.
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        [0, card_top - 6, SIZE, SIZE], radius=44, fill=(15, 23, 42, 70)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(shadow, (0, 0), shadow)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle([0, card_top, SIZE, SIZE + 60], radius=44, fill=WHITE)

    pad = 76
    max_w = SIZE - 2 * pad

    # --- Brand lockup chip over the hero (top-left). ---------------------- #
    chip_font = _font(34, weight=700)
    chip_label_w = draw.textbbox((0, 0), BRAND, font=chip_font)[2]
    chip_h, dot_r = 64, 9
    chip_w = 34 + dot_r * 2 + 14 + chip_label_w + 30
    chip = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(chip)
    cdraw.rounded_rectangle(
        [40, 40, 40 + chip_w, 40 + chip_h], radius=chip_h // 2, fill=(15, 23, 42, 165)
    )
    cy = 40 + chip_h // 2
    cdraw.ellipse(
        [40 + 26, cy - dot_r, 40 + 26 + dot_r * 2, cy + dot_r], fill=(96, 165, 250)
    )
    cdraw.text(
        (40 + 26 + dot_r * 2 + 14, cy), BRAND, font=chip_font, fill=WHITE,
        anchor="lm",
    )
    canvas.paste(chip, (0, 0), chip)

    # --- CTA pill (anchored to the bottom). ------------------------------- #
    cta_font = _font(33, weight=700)
    ctab = draw.textbbox((0, 0), cta, font=cta_font)
    cta_w, cta_h = ctab[2] - ctab[0], ctab[3] - ctab[1]
    pill_h = 76
    pill_w = cta_w + 70
    pill_x0, pill_y0 = pad, SIZE - pad - pill_h
    draw.rounded_rectangle(
        [pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h],
        radius=pill_h // 2, fill=BLUE,
    )
    draw.text(
        (pill_x0 + pill_w // 2, pill_y0 + pill_h // 2), cta,
        font=cta_font, fill=WHITE, anchor="mm",
    )

    # --- "14 хоног үнэгүй" tag next to the CTA. --------------------------- #
    tag_text = "14 хоног үнэгүй"
    tag_font = _font(27, weight=600)
    tagb = draw.textbbox((0, 0), tag_text, font=tag_font)
    tag_w = tagb[2] - tagb[0] + 44
    tag_x0 = pill_x0 + pill_w + 20
    if tag_x0 + tag_w <= SIZE - pad:
        draw.rounded_rectangle(
            [tag_x0, pill_y0, tag_x0 + tag_w, pill_y0 + pill_h],
            radius=pill_h // 2, fill=LIGHT_BLUE,
        )
        draw.text(
            (tag_x0 + tag_w // 2, pill_y0 + pill_h // 2), tag_text,
            font=tag_font, fill=BLUE, anchor="mm",
        )

    # --- Headline + subhead, adaptively sized to fit the card. ------------ #
    text_top = card_top + 64
    text_bottom = pill_y0 - 28
    avail_h = text_bottom - text_top

    head_size = 60
    while head_size >= 38:
        head_font = _font(head_size, weight=800)
        head_lines = _wrap(draw, headline, head_font, max_w)
        head_lh = int(_text_h(draw, head_font) * 1.18) + 8

        sub_lines, sub_lh = [], 0
        if subhead:
            sub_font = _font(max(24, int(head_size * 0.5)), weight=500)
            sub_lines = _wrap(draw, subhead, sub_font, max_w)
            sub_lh = int(_text_h(draw, sub_font) * 1.25) + 4

        total = head_lh * len(head_lines)
        if sub_lines:
            total += 18 + sub_lh * len(sub_lines)

        if len(head_lines) <= 3 and len(sub_lines) <= 2 and total <= avail_h:
            break
        head_size -= 4

    y = text_top
    for line in head_lines:
        draw.text((pad, y), line, font=head_font, fill=NAVY)
        y += head_lh
    if sub_lines:
        y += 18
        for line in sub_lines:
            draw.text((pad, y), line, font=sub_font, fill=GRAY)
            y += sub_lh

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
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
        content = generate_content(angle)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Content generation failed: {exc}")
        sys.exit(1)
    print(f"📝 Headline: {content['headline']}")
    print(f"   Subhead : {content['subhead']}")
    print(f"   CTA     : {content['cta']}")
    print(f"🖌️  Scene   : {content['image_scene']}")

    # 2) Refresh token, then derive the Page Access Token used for all posts.
    token = refresh_token()
    try:
        page_token = get_page_token(token, FACEBOOK_PAGE_ID)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Could not get Page Access Token: {exc}")
        sys.exit(1)

    # 3) Generate textless hero with Stability, then compose the poster.
    try:
        base_png = generate_image(content["image_scene"])
        image_bytes = compose_poster(
            base_png, content["headline"], content["subhead"], content["cta"]
        )
        print(f"🎨 Poster composed ({len(image_bytes)} bytes).")
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
    fb_ok = post_to_facebook(page_token, image_url, content["caption"])
    ig_ok = post_to_instagram(page_token, image_url, content["caption"])

    # 6) Summary.
    print("-" * 64)
    print("SUMMARY")
    print(f"  Angle    : {angle}")
    print(f"  Headline : {content['headline']}")
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
