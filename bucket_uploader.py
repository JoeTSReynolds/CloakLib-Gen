#!/usr/bin/env python3
import argparse
import csv
import os
import sys
import boto3
from collections import defaultdict
from cloaklib import CloakingLibrary
import regex as re

# -----------------------------------------------------------------------------
# CONFIG: target quotas per class
DATASET_REQUIREMENTS = CloakingLibrary.DATASET_REQUIREMENTS

# mapping from CSV field values to folder names
EXPR_MAP = {"Smile": "Smiling", "Smiling": "Smiling", "Neutral": "Neutral"}
OBSTR_MAP = {"Yes": "WithObstruction", "No": "NoObstruction"}
# Group? Yes => Multiple, else Single
def map_group(v): return None if v == "" else ("Multiple" if v.strip().lower() == "yes" else "Single")
def map_gender(v): return None if v == "" else (v if v in ("M", "F") else "Other")
def map_expression(v): return None if v == "" else (EXPR_MAP.get(v, "Other"))
def map_obstruction(v): return None if v == "" else (OBSTR_MAP.get(v, "NoObstruction"))

def wipe_dataset(s3, bucket, prefix="Dataset/"):
    """
    Recursively delete EVERYTHING under prefix in the given bucket.
    """
    paginator = s3.get_paginator("list_objects_v2")
    print(f"[RESET] Deleting all objects under s3://{bucket}/{prefix} …")
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".mp4")):
                to_delete.append({"Key": key})
            # flush every 1000 keys
            if len(to_delete) == 1000:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
                to_delete = []
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
    print("[RESET] Done.")

def build_current_counts(s3, bucket):
    """
    Walk all existing objects under 'Dataset/' in the bucket,
    match only those of the form:
      Dataset/{Cloaked|Uncloaked}/{Images|Videos}/{Category}/{Value}/filename
    and tally per Images|Videos → Category → Value.
    """
    paginator = s3.get_paginator("list_objects_v2")
    # prepare empty counts
    counts = {
        "Images": defaultdict(lambda: defaultdict(int)),
        "Videos": defaultdict(lambda: defaultdict(int)),
    }
    # regex to match and capture: type_plural, category, value
    pattern = re.compile(
        r"^Dataset/Uncloaked/"
        r"(Images|Videos)/"     # <- group 1: plural type
        r"([^/]+)/"             # <- group 2: Category
        r"([^/]+)/"             # <- group 3: Value
        r"[^/]+$"               # then the filename
    )

    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            m = pattern.match(key)
            if not m:
                # not in one of the exact leaf folders
                continue

            type_plural, category, value = m.groups()
            # only count if this category/value is in your requirements
            if (
                category in DATASET_REQUIREMENTS[type_plural]
                and value in DATASET_REQUIREMENTS[type_plural][category]
            ):
                counts[type_plural][category][value] += 1

    return counts

# -------------------------------------------------------------------
def pick_target_folder(counts, item_type, labels):
    """
    Given current counts and this item's labels dict:
    compute fill ratios for each category and choose lowest.
    Returns (category, value).
    """
    best = (None, None, float('inf'))  # (cat, val, ratio)
    reqs = DATASET_REQUIREMENTS[item_type]
    for cat, cat_reqs in reqs.items():
        val = labels[cat]
        if val not in cat_reqs:
            # skip unknown
            continue
        have = counts[item_type][cat].get(val, 0)
        need = cat_reqs[val]
        ratio = have / float(need)
        if ratio < best[2]:
            best = (cat, val, ratio)
    return best[0], best[1]

# -------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser("bucket_uploader.py")
    p.add_argument("--bucket-name", required=True)
    p.add_argument("--csv", help="CSV file (skip first 2 lines)")
    p.add_argument("--data", help="Folder with <name>.jpg/.mp4")
    p.add_argument(
        "--reset",
        action="store_true",
        help="Delete EVERYTHING under Dataset/ in the bucket and exit",
    )
    args = p.parse_args()

    s3 = boto3.client("s3")
    bucket = args.bucket_name

    if args.reset:
        wipe_dataset(s3, bucket)
        sys.exit(0)

    if not args.csv or not args.data:
        print("[ERROR] --csv and --data are required", file=sys.stderr)
        sys.exit(1)

    print("Building counts from S3...")
    counts = build_current_counts(s3, bucket)
    print("Current counts:", counts)

    # open CSV, skip first two lines
    with open(args.csv, newline="", encoding="utf-8") as f:
        # skip a line - first line is nothing interesting, second line is header
        next(f)
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Image Name"].strip()
            media = row["Image/Video"].strip()
            cloaked = row.get("Cloaking?", "").strip().lower() == "yes"
            in_s3 = row.get("In S3?", "").strip().lower() == "yes"
            if in_s3:
                continue

            ext = ".jpg" if media.lower() == "image" else ".mp4"
            local_path = os.path.join(args.data, name + ext)
            if not os.path.isfile(local_path):
                print(f"[WARN] file not found: {local_path}", file=sys.stderr)
                continue

            # map all labels into our folder names
            labels = {
                "Gender": map_gender(row.get("Gender?", "").strip()),
                "Age": row.get("Age?", "").strip() or None,
                "Race": row.get("Race?", "").strip() or None,
                "Expression": map_expression(row.get("Expression?", "").strip()),
                "Obstruction": map_obstruction(row.get("Obstruction?", "").strip()),
                "Groups": map_group(row.get("Group?", "").strip()),
            }

            type_plural = "Images" if media.lower() == "image" else "Videos"
            clr = "Cloaked" if cloaked else "Uncloaked"

            # decide best category/value
            cat, val = pick_target_folder(counts, type_plural, labels)
            if cat is None:
                print(f"[ERROR] no valid category for {name}, skipping", file=sys.stderr)
                continue

            # form S3 key
            key_prefix = f"Dataset/{clr}/{type_plural}/{cat}/{val}/"
            key = key_prefix + os.path.basename(local_path)

            # upload
            s3.upload_file(local_path, bucket, key)
            # update our tally
            counts[type_plural][cat][val] += 1

            print(f"Uploaded {name + ext} → s3://{bucket}/{key}")

if __name__ == "__main__":
    main()
