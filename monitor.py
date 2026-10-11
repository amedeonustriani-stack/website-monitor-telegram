#!/usr/bin/env python3
"""
website-monitor-telegram
------------------------
Checks a web page on a schedule, picks out the items that match your rules
and sends them to you on Telegram. It remembers what it already sent, so you
never get the same alert twice, and it writes a CSV log of every item it saw
with the reason it was kept or dropped.

Works on pages whose items are present in the HTML the server sends.
It does not log in anywhere and does not try to get around blocks.

Usage:
    python monitor.py --config config.json            # run forever
    python monitor.py --config config.json --once     # one check, then exit
    python monitor.py --config config.json --once --dry-run   # print, don't send
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

MIN_INTERVAL_MINUTES = 5          # be polite: never hit a site more often than this
USER_AGENT = "website-monitor-telegram/1.0 (personal alert bot)"
LOG_FIELDS = ["time", "item", "price", "kept", "reason", "link"]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_price(text):
    """Turn '1.299,00 EUR', 'EUR 189', '$1,299.50' or '189' into a float.
    Returns None when there is no number in the text.
    A group of exactly three digits after the only separator ('1.299' or
    '1,299') is read as thousands, which is what it means in a price."""
    if not text:
        return None
    m = re.search(r"\d[\d.,\s]*", text)
    if not m:
        return None
    s = re.sub(r"\s", "", m.group(0)).rstrip(".,")
    if "," in s and "." in s:
        # the separator that comes last is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        head, _, tail = s.rpartition(sep)
        if s.count(sep) > 1 or len(tail) == 3:
            s = s.replace(sep, "")
        else:
            s = head + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def append_log(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


# --------------------------------------------------------------------------
# fetching and reading the page
# --------------------------------------------------------------------------

def fetch(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    r.raise_for_status()
    return r.text


def read_items(html, cfg):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for node in soup.select(cfg["item_selector"]):
        title_node = node.select_one(cfg["title_selector"])
        if title_node is None:
            continue
        title = title_node.get_text(" ", strip=True)
        price_text = ""
        if cfg.get("price_selector"):
            p = node.select_one(cfg["price_selector"])
            price_text = p.get_text(" ", strip=True) if p else ""
        link = ""
        link_node = node.select_one(cfg.get("link_selector") or cfg["title_selector"])
        if link_node is not None and link_node.get("href"):
            link = urljoin(cfg["url"], link_node["href"])
        items.append({"title": title, "price_text": price_text,
                      "price": parse_price(price_text), "link": link})
    return items


# --------------------------------------------------------------------------
# the rules: returns (keep?, reason)
# --------------------------------------------------------------------------

def decide(item, cfg):
    title = item["title"].lower()
    include = [w.lower() for w in cfg.get("include_words", [])]
    exclude = [w.lower() for w in cfg.get("exclude_words", [])]

    if include and not any(w in title for w in include):
        return False, "dropped: none of the wanted words in the title"
    for w in exclude:
        if w in title:
            return False, f"dropped: contains excluded word '{w}'"
    price = item["price"]
    max_price, min_price = cfg.get("max_price"), cfg.get("min_price")
    if (max_price is not None or min_price is not None) and price is None:
        return False, "dropped: no price found, cannot check the price limit"
    if max_price is not None and price > max_price:
        return False, f"dropped: price {price:g} above your limit {max_price:g}"
    if min_price is not None and price < min_price:
        return False, f"dropped: price {price:g} below your minimum {min_price:g}"
    return True, "match"


# --------------------------------------------------------------------------
# telegram
# --------------------------------------------------------------------------

def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                           "(see README), or run with --dry-run.")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
        timeout=20,
    )
    if r.status_code != 200:
        # never print the token; the status and Telegram's message are enough
        raise RuntimeError(f"Telegram answered {r.status_code}: {r.text[:200]}")


def format_message(item):
    lines = ["NEW MATCH", item["title"]]
    if item["price_text"]:
        lines.append(item["price_text"])
    if item["link"]:
        lines.append(item["link"])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# one check
# --------------------------------------------------------------------------

def run_once(cfg, dry_run):
    state_path = cfg.get("state_file", "seen.json")
    log_path = cfg.get("log_file", "log.csv")
    seen = load_json(state_path, None)
    first_run = seen is None
    seen = seen or {}

    html = fetch(cfg["url"])
    items = read_items(html, cfg)
    if not items:
        print(f"[{now()}] No items found. Check item_selector / title_selector "
              f"in your config, or the page may load its content with JavaScript.")
        return

    sent = 0
    for item in items:
        key = item["link"] or item["title"]
        if key in seen:
            continue
        keep, reason = decide(item, cfg)
        row = {"time": now(), "item": item["title"], "price": item["price_text"],
               "kept": "yes" if keep else "no", "reason": reason, "link": item["link"]}

        if keep and first_run and not cfg.get("send_existing_on_first_run", False):
            row["kept"], row["reason"] = "no", "baseline: already on the page at the first run"
            keep = False

        if keep:
            try:
                if dry_run:
                    print("--- (dry run, not sent) ---\n" + format_message(item))
                else:
                    send_telegram(format_message(item))
                sent += 1
            except Exception as e:           # do not mark as seen: retry next time
                print(f"[{now()}] Could not send '{item['title']}': {e}")
                continue

        append_log(log_path, row)
        seen[key] = {"first_seen": now(), "kept": row["kept"]}

    save_json(state_path, seen)
    print(f"[{now()}] Checked {len(items)} items, sent {sent}.")


def main():
    ap = argparse.ArgumentParser(description="Website monitor with Telegram alerts")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--once", action="store_true", help="check once and exit")
    ap.add_argument("--dry-run", action="store_true", help="print matches instead of sending")
    args = ap.parse_args()

    cfg = load_json(args.config, None)
    if cfg is None:
        sys.exit(f"Config file not found: {args.config} (copy config.example.json)")
    for k in ("url", "item_selector", "title_selector"):
        if not cfg.get(k):
            sys.exit(f"Missing '{k}' in {args.config}")

    interval = max(float(cfg.get("interval_minutes", 15)), MIN_INTERVAL_MINUTES)
    while True:
        try:
            run_once(cfg, args.dry_run)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"[{now()}] The site answered {code}. Not retrying faster; "
                  f"if this is 403 or 429 the site does not want automated visits.")
        except requests.RequestException as e:
            print(f"[{now()}] Network problem: {e}")
        if args.once:
            break
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
