#!/usr/bin/env python3
"""
Publish one episode (a brief or a tutor lesson) into the shared daily-queue
podcast feed. Safe for multiple independent sessions to call concurrently
against the same repo: it pulls immediately before committing and retries
once on a push race.

Usage:
  python3 publish_episode.py \
    --repo /path/to/local/clone/of/daily-queue \
    --audio /path/to/episode.mp3 \
    --slug 2026-08-03-brief \
    --title "Daily Brief — August 3, 2026" \
    --category Brief \
    --pubdate "2026-08-03T11:30:00Z" \
    --description "A new blood test that predicts all-cause mortality..."

--category is a free-text label shown in the feed/page, e.g. "Brief" or
"Tutor · Spanish · Unit 4". Every episode is its own standalone audio file —
this script never concatenates or overwrites audio, it only ever adds one
new <item> and one new file under audio/.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def rfc822(pubdate_str):
    # Accept either ISO 8601 (2026-08-03T11:30:00Z) or already-RFC822.
    try:
        dt = datetime.fromisoformat(pubdate_str.replace("Z", "+00:00"))
    except ValueError:
        dt = parsedate_to_datetime(pubdate_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="local path to the cloned daily-queue repo")
    p.add_argument("--audio", required=True, help="path to the mp3 to publish")
    p.add_argument("--slug", required=True, help="filesystem-safe unique id, e.g. 2026-08-03-brief")
    p.add_argument("--title", required=True)
    p.add_argument("--category", required=True, help='e.g. "Brief" or "Tutor · Spanish · Unit 4"')
    p.add_argument("--pubdate", required=True, help="ISO 8601 UTC, e.g. 2026-08-03T11:30:00Z")
    p.add_argument("--description", default="")
    p.add_argument("--base-url", default="https://eaboussouan.github.io/daily-queue")
    p.add_argument("--push-retries", type=int, default=3)
    args = p.parse_args()

    repo = args.repo
    audio_src = args.audio
    if not os.path.isfile(audio_src):
        sys.exit(f"audio file not found: {audio_src}")

    audio_dir = os.path.join(repo, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    dest_filename = f"{args.slug}.mp3"
    dest_path = os.path.join(audio_dir, dest_filename)

    for attempt in range(1, args.push_retries + 1):
        # Always start from the latest remote state before editing feed.xml,
        # so two sessions publishing around the same time don't clobber
        # each other's <item> entries.
        pull = run(["git", "pull", "--rebase", "origin", "main"], cwd=repo)
        if pull.returncode != 0:
            print(pull.stdout, pull.stderr, file=sys.stderr)
            sys.exit("git pull failed")

        shutil.copyfile(audio_src, dest_path)
        size_bytes = os.path.getsize(dest_path)

        feed_path = os.path.join(repo, "feed.xml")
        tree = ET.parse(feed_path)
        root = tree.getroot()
        channel = root.find("channel")

        # Skip if this slug was already published (idempotent re-run).
        existing_guids = {el.text for el in channel.findall("guid")}
        guid_value = args.slug
        already = any(
            item.find("guid") is not None and item.find("guid").text == guid_value
            for item in channel.findall("item")
        )
        if not already:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = args.title
            ET.SubElement(item, "description").text = args.description
            ET.SubElement(item, "pubDate").text = rfc822(args.pubdate)
            ET.SubElement(item, "category").text = args.category
            guid = ET.SubElement(item, "guid")
            guid.set("isPermaLink", "false")
            guid.text = guid_value
            enclosure = ET.SubElement(item, "enclosure")
            enclosure.set("url", f"{args.base_url}/audio/{dest_filename}")
            enclosure.set("length", str(size_bytes))
            enclosure.set("type", "audio/mpeg")

            # Keep items newest-first for readability; podcast apps re-sort
            # by pubDate regardless.
            items = channel.findall("item")
            for it in items:
                channel.remove(it)

            def keyfn(it):
                try:
                    return parsedate_to_datetime(it.find("pubDate").text)
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)

            items.sort(key=keyfn, reverse=True)
            for it in items:
                channel.append(it)

            tree.write(feed_path, encoding="UTF-8", xml_declaration=True)

        run(["git", "add", "-A"], cwd=repo)
        commit = run(["git", "commit", "-m", f"Add episode: {args.title}"], cwd=repo)
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
            print(commit.stdout, commit.stderr, file=sys.stderr)
            sys.exit("git commit failed")

        push = run(["git", "push", "origin", "main"], cwd=repo)
        if push.returncode == 0:
            print(f"published: {args.title}")
            print(f"audio: {args.base_url}/audio/{dest_filename}")
            print(f"feed: {args.base_url}/feed.xml")
            return
        else:
            print(f"push attempt {attempt} failed, retrying...", file=sys.stderr)
            time.sleep(2)

    sys.exit("git push failed after retries")


if __name__ == "__main__":
    main()
