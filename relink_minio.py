#!/usr/bin/env python3
"""
Reconnect lesson files in MinIO to bootcamp.content after a database reload.

Uploads are stored under fixed keys built from the lesson id, so this lists the
bucket and writes each key back onto its lesson:

  videos/dc/{videoid}.mp4                  -> content.miniokey
  documents/dc/{videoid}.pdf               -> content.pdfkey
  documents/dc/instructions/{videoid}.pdf  -> content.instructionskey

Database: RAILWAY_MYSQL_URL if set, otherwise the local MYSQL_* settings.
MinIO:    MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_SECURE /
          MINIO_BUCKET (variables set on the command line win over .env).

  # Railway: preview, then apply
  RAILWAY_MYSQL_URL='mysql://root:PASSWORD@sakura.proxy.rlwy.net:38784' \
  MINIO_ENDPOINT='bucket-production-3e59.up.railway.app' MINIO_SECURE=true \
  MINIO_ACCESS_KEY='...' MINIO_SECRET_KEY='...' MINIO_BUCKET='aari-videos' \
    python relink_minio.py            # shows what would change
    python relink_minio.py --apply    # (same variables) writes the changes

A lesson is only updated when its column is empty, still says pending/...,
or points at an object that is not in the bucket. Valid links are left alone.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import pymysql

import miniIO
from push_to_railway import local_kwargs, remote_kwargs

PDF_PREFIX = os.getenv("MINIO_PDF_PREFIX", "documents/dc").strip("/")
COLUMN_PATTERNS = {
    "miniokey": re.compile(r"^videos/dc/(\d+)\.mp4$"),
    "pdfkey": re.compile(rf"^{re.escape(PDF_PREFIX)}/(\d+)\.pdf$"),
    "instructionskey": re.compile(rf"^{re.escape(PDF_PREFIX)}/instructions/(\d+)\.pdf$"),
}
COLUMN_LABELS = {
    "miniokey": "lesson video(s)",
    "pdfkey": "lesson PDF(s)",
    "instructionskey": "assignment instructions PDF(s)",
}


def bucket_keys() -> tuple[dict[str, dict[int, str]], set[str]]:
    """Return ({column: {videoid: key}}, every object key)."""
    client = miniIO.get_client()
    bucket = miniIO.get_bucket()
    if not client.bucket_exists(bucket):
        sys.exit(f"MinIO bucket {bucket!r} does not exist at {os.getenv('MINIO_ENDPOINT')}.")
    found: dict[str, dict[int, str]] = {column: {} for column in COLUMN_PATTERNS}
    all_keys: set[str] = set()
    for prefix in ("videos/dc/", f"{PDF_PREFIX}/"):
        for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
            key = obj.object_name
            all_keys.add(key)
            for column, pattern in COLUMN_PATTERNS.items():
                if match := pattern.match(key):
                    found[column][int(match.group(1))] = key
                    break
    return found, all_keys


def needs_update(current: str | None, found: str, all_keys: set[str]) -> bool:
    if current == found:
        return False
    return not current or current.startswith("pending/") or current not in all_keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default is a preview)")
    args = parser.parse_args()

    on_railway = bool(os.getenv("RAILWAY_MYSQL_URL", "").strip())
    db = remote_kwargs() if on_railway else local_kwargs()
    print(f"Database: {db['user']}@{db['host']}:{db['port']} ({'Railway' if on_railway else 'local'})")
    print(f"MinIO:    {os.getenv('MINIO_ENDPOINT', 'localhost:9000')} bucket {miniIO.get_bucket()!r}\n")

    found, all_keys = bucket_keys()
    summary = ", ".join(f"{len(found[c])} {COLUMN_LABELS[c]}" for c in COLUMN_PATTERNS)
    print(f"Bucket has {summary}.\n")

    conn = pymysql.connect(**db, database="bootcamp")
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                f"SELECT videoid, title, {', '.join(COLUMN_PATTERNS)} FROM content ORDER BY videoid"
            )
            lessons = {row["videoid"]: row for row in cur.fetchall()}

        changes: list[tuple[int, str, str]] = []
        for videoid, lesson in lessons.items():
            for column in COLUMN_PATTERNS:
                key = found[column].get(videoid)
                if key and needs_update(lesson[column], key, all_keys):
                    changes.append((videoid, column, key))
                    print(f"  lesson {videoid} ({lesson['title']}): {column} {lesson[column] or '(empty)'} -> {key}")

        changed = {(videoid, column) for videoid, column, _ in changes}
        broken = [
            (videoid, column, lesson[column])
            for videoid, lesson in lessons.items()
            for column in COLUMN_PATTERNS
            if lesson[column]
            and not lesson[column].startswith("pending/")
            and lesson[column] not in all_keys
            and (videoid, column) not in changed
        ]
        orphans = sorted(
            key
            for keys in found.values()
            for videoid, key in keys.items()
            if videoid not in lessons
        )

        if not changes:
            print("  Nothing to relink; every file in the bucket is already connected.")
        if broken:
            print("\nLessons pointing at files that are not in the bucket (re-upload these):")
            for videoid, column, key in broken:
                print(f"  lesson {videoid}: {column} = {key}")
        if orphans:
            print("\nFiles with no matching lesson id (left untouched):")
            for key in orphans:
                print(f"  {key}")

        if not changes:
            return
        if not args.apply:
            print(f"\nPreview only: {len(changes)} change(s). Re-run with --apply to write them.")
            return
        with conn.cursor() as cur:
            for videoid, column, key in changes:
                cur.execute(f"UPDATE content SET `{column}` = %s WHERE videoid = %s", (key, videoid))
        conn.commit()
        print(f"\nRelinked {len(changes)} file(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
