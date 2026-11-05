"""One-time helper: turns a short-lived user token into a NEVER-EXPIRING Page token.

Run on your own computer:  python get_page_token.py
It asks for your App ID, App Secret and the user token from the Graph API Explorer,
then prints FB_PAGE_ID and FB_PAGE_TOKEN for each Page you manage.
Nothing is saved or sent anywhere except to graph.facebook.com.
"""
import getpass

import requests

GRAPH = "https://graph.facebook.com/v26.0"

app_id = input("App ID: ").strip()
app_secret = getpass.getpass("App Secret (hidden): ").strip()
short = getpass.getpass("User token from Graph API Explorer (hidden): ").strip()

r = requests.get(f"{GRAPH}/oauth/access_token", params={
    "grant_type": "fb_exchange_token", "client_id": app_id,
    "client_secret": app_secret, "fb_exchange_token": short}, timeout=30)
r.raise_for_status()
long_user = r.json()["access_token"]

pages = requests.get(f"{GRAPH}/me/accounts", params={
    "access_token": long_user, "fields": "id,name,access_token"}, timeout=30)
pages.raise_for_status()
for p in pages.json().get("data", []):
    print("\n" + "=" * 60)
    print(f"Page:          {p['name']}")
    print(f"FB_PAGE_ID:    {p['id']}")
    print(f"FB_PAGE_TOKEN: {p['access_token']}")
print("\nCheck it never expires: paste the token into developers.facebook.com/tools/debug/accesstoken")
