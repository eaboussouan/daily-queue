#!/usr/bin/env python3
"""Rebuild feed.xml from episodes/*.json + audio/*.mp3.

This is the ONLY writer of feed.xml, and it runs in GitHub Actions on every
push. Publishers never touch feed.xml — they only ADD an mp3 to audio/ and a
metadata json to episodes/. That makes the feed derived, deterministic state:
it can always be regenerated, and no publisher can corrupt or lose episodes.

Episode json schema (episodes/<slug>.json):
  {"slug","title","description","category","pubdate" (ISO 8601 UTC),"audio" (filename in audio/)}
"""
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "https://eaboussouan.github.io/daily-queue"


def main():
    episodes = []
    ep_dir = os.path.join(ROOT, "episodes")
    for name in sorted(os.listdir(ep_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(ep_dir, name)) as f:
            ep = json.load(f)
        audio_path = os.path.join(ROOT, "audio", ep["audio"])
        if not os.path.isfile(audio_path):
            print(f"WARNING: {name}: audio file {ep['audio']} missing, skipping", file=sys.stderr)
            continue
        ep["_size"] = os.path.getsize(audio_path)
        ep["_dt"] = datetime.fromisoformat(ep["pubdate"].replace("Z", "+00:00"))
        episodes.append(ep)

    episodes.sort(key=lambda e: e["_dt"], reverse=True)

    items = []
    for ep in episodes:
        items.append(f"""    <item>
      <title>{escape(ep["title"])}</title>
      <description>{escape(ep.get("description", ""))}</description>
      <pubDate>{format_datetime(ep["_dt"])}</pubDate>
      <category>{escape(ep["category"])}</category>
      <guid isPermaLink="false">{escape(ep["slug"])}</guid>
      <enclosure url="{BASE_URL}/audio/{escape(ep["audio"])}" length="{ep["_size"]}" type="audio/mpeg" />
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Eric's Daily Queue</title>
    <link>{BASE_URL}/</link>
    <description>Daily AI briefs and tutor lessons, one file per episode, nothing ever expires.</description>
    <language>en-us</language>
    <itunes:author>Eric</itunes:author>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""
    with open(os.path.join(ROOT, "feed.xml"), "w") as f:
        f.write(feed)
    print(f"feed.xml rebuilt: {len(episodes)} episodes")


if __name__ == "__main__":
    main()
