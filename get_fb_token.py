#!/usr/bin/env python3
"""
One-off helper: turn a short-lived Facebook USER token into a PERMANENT
Page Access Token (the kind that never expires) for FB_PAGE_ACCESS_TOKEN.

WHY: Graph API Explorer hands you a short-lived user token that dies in ~1-2
hours. A Page token derived from a *long-lived* user token does not expire, so
it's what the poster should use.

HOW TO USE (run locally, not in CI):

  1. Go to https://developers.facebook.com/tools/explorer
     - Pick your app (top-right).
     - Click "Generate Access Token" and grant these permissions:
         pages_show_list, pages_manage_posts, pages_read_engagement,
         instagram_basic, instagram_content_publish, business_management
     - Copy the User token it shows.

  2. Run this script (PowerShell):
         $env:FB_APP_ID="..."          # same as your GitHub secret
         $env:FB_APP_SECRET="..."      # same as your GitHub secret
         $env:FB_USER_TOKEN="paste short-lived user token here"
         python get_fb_token.py

  3. It prints a PERMANENT Page Access Token. Copy it into the GitHub secret
     FB_PAGE_ACCESS_TOKEN (Settings -> Secrets and variables -> Actions).

This only needs to be redone if you change the app or revoke access.
"""

import os
import sys

import requests

GRAPH = "https://graph.facebook.com/v19.0"
PAGE_ID = "1079728475218630"  # the Sello AI / Nexon Shop AI page


def main():
    app_id = os.environ.get("FB_APP_ID", "").strip()
    app_secret = os.environ.get("FB_APP_SECRET", "").strip()
    user_token = os.environ.get("FB_USER_TOKEN", "").strip()

    if not (app_id and app_secret and user_token):
        print("❌ Set FB_APP_ID, FB_APP_SECRET and FB_USER_TOKEN first. "
              "See the instructions at the top of this file.")
        sys.exit(1)

    # 1) Exchange the short-lived user token for a long-lived one (~60 days).
    print("🔄 Exchanging for a long-lived user token...")
    resp = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": user_token,
        },
        timeout=30,
    )
    data = resp.json()
    if resp.status_code != 200 or not data.get("access_token"):
        print(f"❌ Long-lived exchange failed ({resp.status_code}): {data}")
        sys.exit(1)
    long_user_token = data["access_token"]
    print("✅ Got long-lived user token.")

    # 2) Pull the Page token. A page token from a long-lived user token does
    #    NOT expire — that's the one we want.
    resp = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": long_user_token},
        timeout=30,
    )
    data = resp.json()
    if resp.status_code != 200:
        print(f"❌ /me/accounts failed ({resp.status_code}): {data}")
        sys.exit(1)

    pages = data.get("data", [])
    if not pages:
        print("❌ No pages returned. Did you grant pages_show_list + "
              "pages_manage_posts on the right app/account?")
        sys.exit(1)

    target = next((p for p in pages if p.get("id") == PAGE_ID), None)
    if not target:
        print(f"⚠️  Page {PAGE_ID} not in your pages. Available pages:")
        for p in pages:
            print(f"    - {p.get('name')}  (id={p.get('id')})")
        print("Update PAGE_ID in this script if you meant a different page.")
        sys.exit(1)

    page_token = target["access_token"]
    print("\n" + "=" * 64)
    print(f"✅ PERMANENT Page Access Token for '{target.get('name')}':\n")
    print(page_token)
    print("\nPaste this into the GitHub secret FB_PAGE_ACCESS_TOKEN.")
    print("=" * 64)


if __name__ == "__main__":
    main()
