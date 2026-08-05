#!/usr/bin/env python3
"""Publish one episode (a brief or a tutor lesson) to the shared daily-queue.

v2 design: publishers only ADD two files — audio/<slug>.mp3 and
episodes/<slug>.json — and push. They NEVER touch feed.xml; a GitHub Action
(.github/workflows/build-feed.yml) rebuilds it from episodes/ on every push.
Concurrent publishers can't conflict (different filenames) and no publisher
can ever corrupt or lose the feed.

Auth: git credentials are injected by the sandbox proxy for repos attached to
the session's Claude GitHub App — no token needed in this script. If push
fails with an access error, the repo needs to be (re)attached to the Claude
GitHub App at github.com/settings/installations.

Usage:
  python3 publish_episode.py \
    --repo /home/claude/daily-queue \
    --audio /path/to/episode.mp3 \
    --slug 2026-08-05-brief \
    --title "Daily Brief — August 5, 2026" \
    --category Brief \
    --pubdate "2026-08-05T11:30:00Z" \
    --description "One-sentence teaser."

Every episode is its own standalone audio file — this script never
concatenates or overwrites audio.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--audio", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--pubdate", required=True, help="ISO 8601 UTC, e.g. 2026-08-05T11:30:00Z")
    p.add_argument("--description", default="")
    p.add_argument("--push-retries", type=int, default=5)
    args = p.parse_args()

    repo = args.repo
    if not os.path.isfile(args.audio):
        sys.exit(f"audio file not found: {args.audio}")

    # Start from current remote state. Local repo state is disposable — the
    # remote is the source of truth and this repo only ever gains files.
    fetch = run(["git", "fetch", "origin", "main"], cwd=repo)
    if fetch.returncode != 0:
        print(fetch.stderr, file=sys.stderr)
        sys.exit("git fetch failed — check that the repo is attached to the "
                 "Claude GitHub App (github.com/settings/installations)")
    run(["git", "reset", "--hard", "origin/main"], cwd=repo)

    audio_dest = os.path.join(repo, "audio", f"{args.slug}.mp3")
    ep_dest = os.path.join(repo, "episodes", f"{args.slug}.json")
    if os.path.exists(ep_dest):
        print(f"episode {args.slug} already published — nothing to do")
        return
    os.makedirs(os.path.dirname(audio_dest), exist_ok=True)
    os.makedirs(os.path.dirname(ep_dest), exist_ok=True)

    shutil.copyfile(args.audio, audio_dest)
    with open(ep_dest, "w") as f:
        json.dump({
            "slug": args.slug,
            "title": args.title,
            "description": args.description,
            "category": args.category,
            "pubdate": args.pubdate,
            "audio": f"{args.slug}.mp3",
        }, f, indent=2, ensure_ascii=False)

    run(["git", "add", audio_dest, ep_dest], cwd=repo)
    commit = run(["git", "commit", "-m", f"Add episode: {args.title}"], cwd=repo)
    if commit.returncode != 0:
        print(commit.stdout, commit.stderr, file=sys.stderr)
        sys.exit("git commit failed")

    for attempt in range(1, args.push_retries + 1):
        push = run(["git", "push", "origin", "main"], cwd=repo)
        if push.returncode == 0:
            print(f"published: {args.title}")
            print("feed rebuild runs automatically via GitHub Actions "
                  "(~1 min): https://eaboussouan.github.io/daily-queue/feed.xml")
            return
        print(f"push attempt {attempt} failed: {push.stderr.strip()[:200]}", file=sys.stderr)
        run(["git", "pull", "--rebase", "origin", "main"], cwd=repo)
        time.sleep(3)

    sys.exit("git push failed after retries — the episode files are committed "
             "locally. Most likely cause: the repo is not attached to the "
             "Claude GitHub App (github.com/settings/installations). Fix "
             "access, then re-run this script (it is idempotent).")


if __name__ == "__main__":
    main()
