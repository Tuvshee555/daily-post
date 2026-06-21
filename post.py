#!/usr/bin/env python3
"""
Nexon Shop AI — social media auto-poster.

On each run it:
  1. Refreshes the FB token (long-lived exchange).
  2. Picks a content template via a day-of-week + time-slot rotation
     (21 slots = 7 days x 3 daily runs, so it never repeats the same
     post twice in a row and each week is different).
  3. Renders a 1080x1080 branded image with Pillow.
  4. Uploads the image to catbox.moe (anonymous) to get a public URL.
  5. Posts the photo to the Facebook Page.
  6. Posts the photo to Instagram (create container -> publish).
  7. Logs exactly what happened.

Designed to run from GitHub Actions. All credentials come from env vars.
"""

import io
import os
import sys
from datetime import datetime, timezone

import requests
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


# --------------------------------------------------------------------------- #
# Content templates
# Each: hook (image headline), body (caption), hashtags.
# 21 templates -> one per (weekday x daily-slot), so a full week never repeats
# and the same post is never used twice in a row.
# --------------------------------------------------------------------------- #
HASHTAGS_CORE = (
    "#AIChatbot #AIAutomation #BusinessAutomation #CustomerService #ChatbotMarketing "
    "#SmallBusiness #Ecommerce #LeadGeneration #DigitalMarketing #AIforBusiness "
    "#CustomerExperience #Sales #Entrepreneur #MarketingTips #Automation "
    "#GrowYourBusiness #AItools #OnlineBusiness #CustomerSupport #SaaS"
)

TEMPLATES = [
    # --- Pain points ---
    {
        "type": "pain",
        "hook": "Still manually answering the same customer questions every day?",
        "body": (
            "Still typing out the same answers over and over? 😩\n\n"
            "\"What are your prices?\"\n"
            "\"Do you deliver?\"\n"
            "\"Is this in stock?\"\n\n"
            "Your team burns hours on questions an AI chatbot could answer "
            "instantly — 24/7, in your brand voice.\n\n"
            "👉 Let Nexon Shop AI handle the repetitive stuff so your team can "
            "focus on closing sales."
        ),
    },
    {
        "type": "pain",
        "hook": "The #1 reason small businesses lose customers online",
        "body": (
            "The #1 reason small businesses lose customers online? ⏱️\n\n"
            "Slow replies.\n\n"
            "79% of customers expect a response within minutes. If you answer "
            "tomorrow, they've already bought from someone else.\n\n"
            "✅ The fix: an AI chatbot that replies in seconds, every time.\n\n"
            "👉 Nexon Shop AI never makes a customer wait."
        ),
    },
    {
        "type": "pain",
        "hook": "Losing sales while you sleep?",
        "body": (
            "Your customers shop at midnight. Does your business answer them? 🌙\n\n"
            "Every unanswered message after hours is a sale walking out the door.\n\n"
            "An AI chatbot works the night shift so you don't have to.\n\n"
            "👉 Nexon Shop AI captures every lead — even at 3am."
        ),
    },
    # --- Outcomes ---
    {
        "type": "outcome",
        "hook": "What if your business replied to every lead in under 3 seconds — at 3am?",
        "body": (
            "Imagine this 👇\n\n"
            "A customer messages you at 3am.\n"
            "In under 3 seconds, they get a warm, accurate reply.\n"
            "They book. They buy. You wake up to new sales. ☀️\n\n"
            "That's not the future — that's an AI chatbot working while you sleep.\n\n"
            "👉 Nexon Shop AI makes it real for your business."
        ),
    },
    {
        "type": "outcome",
        "hook": "Turn every conversation into a sale",
        "body": (
            "What if every customer chat ended in a sale? 💰\n\n"
            "An AI chatbot greets, qualifies, answers objections, and guides "
            "buyers to checkout — automatically.\n\n"
            "No more leads slipping through the cracks.\n\n"
            "👉 Nexon Shop AI turns conversations into customers."
        ),
    },
    {
        "type": "outcome",
        "hook": "Reply to 100 customers at once — without hiring",
        "body": (
            "Black Friday rush? Product going viral? 🚀\n\n"
            "An AI chatbot handles 1 customer or 1,000 — at the same time, "
            "with zero extra staff.\n\n"
            "Scale your support without scaling your payroll.\n\n"
            "👉 Nexon Shop AI grows with you."
        ),
    },
    # --- Education ---
    {
        "type": "education",
        "hook": "5 things AI chatbots do that your team shouldn't waste time on",
        "body": (
            "5 things your team shouldn't be doing manually 👇\n\n"
            "1️⃣ Answering \"what's the price?\" for the 50th time\n"
            "2️⃣ Sharing your hours & location\n"
            "3️⃣ Checking if items are in stock\n"
            "4️⃣ Following up with leads\n"
            "5️⃣ Collecting customer details\n\n"
            "An AI chatbot does all 5 — instantly.\n\n"
            "👉 Free your team with Nexon Shop AI."
        ),
    },
    {
        "type": "education",
        "hook": "How AI chatbots actually grow your revenue",
        "body": (
            "AI chatbots aren't just for support — they sell. 📈\n\n"
            "• Instant replies = fewer lost leads\n"
            "• 24/7 availability = more booked sales\n"
            "• Smart follow-ups = higher conversion\n"
            "• Product recommendations = bigger carts\n\n"
            "It's a salesperson that never sleeps.\n\n"
            "👉 See what Nexon Shop AI can do for you."
        ),
    },
    {
        "type": "education",
        "hook": "AI chatbot vs. live chat: what's the difference?",
        "body": (
            "\"Isn't a chatbot just live chat?\" 🤔 Not even close.\n\n"
            "Live chat = a human, limited hours, one chat at a time.\n"
            "AI chatbot = instant, 24/7, unlimited chats, always on-brand.\n\n"
            "And it hands off to a human when it matters.\n\n"
            "👉 Get the best of both with Nexon Shop AI."
        ),
    },
    # --- Social proof ---
    {
        "type": "social_proof",
        "hook": "Our clients save 10+ hours a week with one AI chatbot setup",
        "body": (
            "10+ hours a week. ⏳\n\n"
            "That's how much time our clients get back after setting up one "
            "AI chatbot.\n\n"
            "No more copy-pasting answers. No more missed messages. Just more "
            "time to grow the business.\n\n"
            "👉 Get those hours back with Nexon Shop AI."
        ),
    },
    {
        "type": "social_proof",
        "hook": "From missed messages to booked sales",
        "body": (
            "Before: messages piling up, leads going cold. 😴\n"
            "After: every customer answered in seconds, sales rolling in. 🎉\n\n"
            "That's the difference one AI chatbot makes for a business.\n\n"
            "👉 Your turn — let Nexon Shop AI set it up for you."
        ),
    },
    {
        "type": "social_proof",
        "hook": "Why businesses are switching to AI chatbots",
        "body": (
            "More and more businesses are making the switch. 🔄\n\n"
            "Why? Because customers expect instant answers, and humans can't be "
            "online 24/7.\n\n"
            "An AI chatbot delivers — consistently, affordably, around the clock.\n\n"
            "👉 Don't get left behind. Talk to Nexon Shop AI."
        ),
    },
    # --- Direct offers / CTA ---
    {
        "type": "offer",
        "hook": "Get an AI chatbot built for your business this week",
        "body": (
            "Want an AI chatbot that actually knows your business? 🤖\n\n"
            "We build it on YOUR products, YOUR FAQs, YOUR voice — and connect "
            "it to Messenger, Instagram & your website.\n\n"
            "Set up in days, not months.\n\n"
            "👉 DM us \"AI\" to get started with Nexon Shop AI."
        ),
    },
    {
        "type": "offer",
        "hook": "Your 24/7 sales assistant is one message away",
        "body": (
            "Ready to stop losing leads? 🚀\n\n"
            "Nexon Shop AI gives your business a 24/7 AI assistant that answers, "
            "sells, and captures every lead automatically.\n\n"
            "No tech skills needed — we handle setup.\n\n"
            "👉 Message us today and we'll get you live."
        ),
    },
    {
        "type": "offer",
        "hook": "Try an AI chatbot for your shop — we'll build the demo",
        "body": (
            "Curious what an AI chatbot would say to YOUR customers? 👀\n\n"
            "We'll build a free demo trained on your shop so you can see it "
            "in action before you commit.\n\n"
            "Zero risk. Real results.\n\n"
            "👉 DM \"DEMO\" and Nexon Shop AI will set it up."
        ),
    },
    # --- FAQ ---
    {
        "type": "faq",
        "hook": "\"Will an AI chatbot sound robotic?\" — Nope.",
        "body": (
            "Common worry: \"Won't it sound like a robot?\" 🤖\n\n"
            "Not anymore. Modern AI chatbots reply naturally, in your brand's "
            "tone, and even switch languages.\n\n"
            "Customers often can't tell — they just love the fast, helpful answers.\n\n"
            "👉 Hear it for yourself with Nexon Shop AI."
        ),
    },
    {
        "type": "faq",
        "hook": "\"Is it hard to set up?\" — We do it for you.",
        "body": (
            "\"Sounds great, but I'm not techy...\" 😅\n\n"
            "Good news: you don't have to be. We build, train, and connect your "
            "AI chatbot for you.\n\n"
            "You just watch the leads come in.\n\n"
            "👉 Let Nexon Shop AI handle the tech."
        ),
    },
    # --- Myth-busting ---
    {
        "type": "myth",
        "hook": "Myth: \"AI chatbots are only for big companies.\"",
        "body": (
            "MYTH: AI chatbots are only for big corporations. ❌\n\n"
            "TRUTH: Small businesses benefit the MOST. 💡\n\n"
            "When you can't afford a 24/7 support team, an AI chatbot levels the "
            "playing field — for a fraction of the cost.\n\n"
            "👉 Nexon Shop AI is built for businesses like yours."
        ),
    },
    {
        "type": "myth",
        "hook": "Myth: \"AI will annoy my customers.\"",
        "body": (
            "MYTH: An AI chatbot will frustrate my customers. ❌\n\n"
            "TRUTH: Customers HATE waiting — not getting instant help. ✅\n\n"
            "A good AI chatbot answers fast, solves problems, and hands off to a "
            "human when needed. That's a better experience, not a worse one.\n\n"
            "👉 Delight your customers with Nexon Shop AI."
        ),
    },
    # --- Comparison ---
    {
        "type": "comparison",
        "hook": "Human-only support vs. AI + human",
        "body": (
            "Support team alone 👇\n"
            "❌ Limited hours\n"
            "❌ Slow during rushes\n"
            "❌ Repetitive burnout\n\n"
            "AI chatbot + your team 👇\n"
            "✅ 24/7 instant replies\n"
            "✅ Handles unlimited chats\n"
            "✅ Humans focus on what matters\n\n"
            "👉 Upgrade your support with Nexon Shop AI."
        ),
    },
    {
        "type": "comparison",
        "hook": "The cost of slow replies vs. an AI chatbot",
        "body": (
            "Do the math 🧮\n\n"
            "Slow replies = lost leads = lost revenue, every single day.\n\n"
            "An AI chatbot costs less than one part-time hire — and never "
            "clocks out.\n\n"
            "The expensive option is doing nothing.\n\n"
            "👉 Start saving with Nexon Shop AI."
        ),
    },
]


def get_template_for_now():
    """Pick a template using weekday + daily time-slot rotation.

    21 templates map to 7 weekdays x 3 daily runs (morning/afternoon/evening),
    so the same post is never used twice in a row and each week differs.
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0 = Monday .. 6 = Sunday

    # Map the run hour to a slot: 0 (morning), 1 (afternoon), 2 (evening).
    hour = now.hour
    if hour < 12:
        slot = 0
    elif hour < 16:
        slot = 1
    else:
        slot = 2

    index = (weekday * 3 + slot) % len(TEMPLATES)
    template = TEMPLATES[index]
    return template, index, weekday, slot


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


# --------------------------------------------------------------------------- #
# Image generation
# --------------------------------------------------------------------------- #
SIZE = 1080
BRAND = "Nexon Shop AI"


def _load_font(size, bold=True):
    """Load a bold TrueType font, trying common Linux/Windows paths."""
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


def _lerp(a, b, t):
    return int(a + (b - a) * t)


def _gradient_background():
    """Vertical dark navy -> deep purple gradient."""
    top = (15, 12, 41)      # #0F0C29 deep navy
    mid = (48, 43, 99)      # #302B63 purple
    bottom = (36, 36, 62)   # #24243E navy-purple

    img = Image.new("RGB", (SIZE, SIZE), top)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        if t < 0.5:
            tt = t / 0.5
            r = _lerp(top[0], mid[0], tt)
            g = _lerp(top[1], mid[1], tt)
            b = _lerp(top[2], mid[2], tt)
        else:
            tt = (t - 0.5) / 0.5
            r = _lerp(mid[0], bottom[0], tt)
            g = _lerp(mid[1], bottom[1], tt)
            b = _lerp(mid[2], bottom[2], tt)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b))
    return img


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


def build_image(hook):
    """Render the 1080x1080 branded image and return PNG bytes."""
    img = _gradient_background()
    draw = ImageDraw.Draw(img)

    margin = 90
    max_width = SIZE - 2 * margin

    # Pick a headline font size that fits without too many lines.
    font_size = 84
    while font_size >= 48:
        font = _load_font(font_size, bold=True)
        lines = _wrap_text(draw, hook, font, max_width)
        line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + 18
        total_h = line_h * len(lines)
        if total_h <= SIZE * 0.6 and len(lines) <= 7:
            break
        font_size -= 6

    # Small accent bar above the headline.
    accent_y = (SIZE - total_h) // 2 - 70
    draw.rounded_rectangle(
        [margin, accent_y, margin + 120, accent_y + 12],
        radius=6, fill=(155, 120, 255),
    )

    # Draw the headline text block (left-aligned, vertically centered).
    y = (SIZE - total_h) // 2
    for line in lines:
        draw.text((margin, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    # Branding bar at the bottom.
    brand_font = _load_font(46, bold=True)
    tag_font = _load_font(30, bold=False)

    # Brand accent dot + name.
    dot_r = 14
    brand_y = SIZE - 130
    draw.ellipse(
        [margin, brand_y + 6, margin + 2 * dot_r, brand_y + 6 + 2 * dot_r],
        fill=(155, 120, 255),
    )
    draw.text((margin + 2 * dot_r + 22, brand_y), BRAND,
              font=brand_font, fill=(255, 255, 255))

    draw.text((margin, brand_y + 58),
              "AI chatbots that sell — 24/7",
              font=tag_font, fill=(190, 185, 220))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Image hosting (catbox.moe — anonymous, no account/API key)
# --------------------------------------------------------------------------- #
def upload_image(image_bytes):
    """Anonymous catbox.moe upload -> public image URL."""
    resp = requests.post(
        "https://catbox.moe/user/api.php",
        data={"reqtype": "fileupload"},
        files={"fileToUpload": ("post.png", image_bytes, "image/png")},
        timeout=60,
    )
    if resp.status_code == 200 and resp.text.startswith("https://"):
        url = resp.text.strip()
        print(f"🖼️  Uploaded to catbox.moe: {url}")
        return url
    raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")


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
    print(f"Nexon Shop AI auto-poster — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 64)

    if not FB_PAGE_ACCESS_TOKEN:
        print("❌ FB_PAGE_ACCESS_TOKEN is missing. Aborting.")
        sys.exit(1)

    # 1) Pick content.
    template, index, weekday, slot = get_template_for_now()
    slot_name = {0: "morning", 1: "afternoon", 2: "evening"}[slot]
    caption = f"{template['body']}\n\n{HASHTAGS_CORE}"
    print(f"📝 Selected template #{index} ({template['type']}) — "
          f"weekday {weekday}, {slot_name} slot")
    print(f"    Hook: {template['hook']}")

    # 2) Refresh token.
    token = refresh_token()

    # 3) Build image.
    try:
        image_bytes = build_image(template["hook"])
        print(f"🎨 Image generated ({len(image_bytes)} bytes).")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Image generation failed: {exc}")
        sys.exit(1)

    # 4) Upload to catbox.moe.
    try:
        image_url = upload_image(image_bytes)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}")
        sys.exit(1)

    # 5) Post to Facebook + Instagram.
    fb_ok = post_to_facebook(token, image_url, caption)
    ig_ok = post_to_instagram(token, image_url, caption)

    # 6) Summary.
    print("-" * 64)
    print("SUMMARY")
    print(f"  Template : #{index} ({template['type']})")
    print(f"  Hook     : {template['hook']}")
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
