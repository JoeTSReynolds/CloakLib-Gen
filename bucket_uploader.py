#!/usr/bin/env python3
import argparse
import csv
import os
import sys
import boto3
from collections import defaultdict
from cloaklib import CloakingLibrary
import regex as re
from io import StringIO

DATASET_REQUIREMENTS = CloakingLibrary.DATASET_REQUIREMENTS

EXPR_MAP = {"Smile": "Smiling", "Smiling": "Smiling", "Neutral": "Neutral"}
OBSTR_MAP = {"Yes": "WithObstruction", "No": "NoObstruction"}

def map_group(v): return None if v == "" else ("Multiple" if v.strip().lower() == "yes" else "Single")
def map_gender(v): return None if v == "" else (v if v in ("M", "F") else "Other")
def map_expression(v): return None if v == "" else (EXPR_MAP.get(v, "Other"))
def map_obstruction(v): return None if v == "" else (OBSTR_MAP.get(v, "NoObstruction"))

def wipe_dataset(s3, bucket, prefix="Dataset/"):
    paginator = s3.get_paginator("list_objects_v2")
    print(f"[RESET] Deleting all objects under s3://{bucket}/{prefix} …")
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".mp4")):
                to_delete.append({"Key": key})
            if len(to_delete) == 1000:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
                to_delete = []
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
    print("[RESET] Done.")

def build_current_counts(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    counts = {
        "Images": defaultdict(lambda: defaultdict(int)),
        "Videos": defaultdict(lambda: defaultdict(int)),
    }
    pattern = re.compile(
        r"^Dataset/Uncloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"[^/]+$"
    )
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Uncloaked/"):
        for obj in page.get("Contents", []):
            m = pattern.match(obj["Key"])
            if not m:
                continue
            typ, category, value = m.groups()
            if category in DATASET_REQUIREMENTS[typ] and value in DATASET_REQUIREMENTS[typ][category]:
                counts[typ][category][value] += 1
    return counts

def build_cloaked_counts(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    counts = {
        "Images": defaultdict(lambda: defaultdict(int)),
        "Videos": defaultdict(lambda: defaultdict(int)),
    }
    pattern = re.compile(
        r"^Dataset/Cloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"[^/]+$"
    )
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Cloaked/"):
        for obj in page.get("Contents", []):
            m = pattern.match(obj["Key"])
            if not m:
                continue
            typ, category, value = m.groups()
            if category in DATASET_REQUIREMENTS[typ] and value in DATASET_REQUIREMENTS[typ][category]:
                counts[typ][category][value] += 1
    return counts

def print_dataset_info(s3, bucket):
    print("[INFO] Building uncloaked counts from S3...")
    uncloaked_counts = build_current_counts(s3, bucket)
    print("[INFO] Building cloaked counts from S3...")
    cloaked_counts = build_cloaked_counts(s3, bucket)
    
    print("\n" + "="*80)
    print("DATASET STATUS INFORMATION")
    print("="*80)
    
    total_uncloaked = 0
    total_required = 0
    
    for media_type in ["Images", "Videos"]:
        print(f"\n{media_type.upper()}:")
        print("-" * 50)
        
        for category in sorted(DATASET_REQUIREMENTS[media_type].keys()):
            print(f"\n  {category}:")
            for value in sorted(DATASET_REQUIREMENTS[media_type][category].keys()):
                uncloaked = uncloaked_counts[media_type][category].get(value, 0)
                required = DATASET_REQUIREMENTS[media_type][category][value]
                cloaked = cloaked_counts[media_type][category].get(value, 0)
                
                total_uncloaked += uncloaked
                total_required += required

                print(f"    {value}: {uncloaked}/{required} uncloaked ({100 * uncloaked/required:.1f}%), {cloaked} cloaked")

    # Calculate and display average ratio
    average_ratio = total_uncloaked / total_required if total_required > 0 else 0
    print("\n" + "="*80)
    print(f"OVERALL STATISTICS:")
    print(f"Total uncloaked files: {total_uncloaked}")
    print(f"Total required files: {total_required}")
    print(f"Average ratio: {average_ratio:.3f} ({average_ratio*100:.1f}%)")
    print("="*80)

def pick_target_folder(counts, item_type, labels):
    best = (None, None, float('inf'))
    reqs = DATASET_REQUIREMENTS[item_type]
    for cat, cat_reqs in reqs.items():
        val = labels.get(cat)
        if val not in cat_reqs:
            continue
        have = counts[item_type][cat].get(val, 0)
        need = cat_reqs[val]
        ratio = have / float(need)
        if ratio < best[2]:
            best = (cat, val, ratio)
    return best[0], best[1]

def parse_labels(row):
    return {
        "Gender": map_gender(row.get("Gender?", "").strip()),
        "Age": row.get("Age?", "").strip() or None,
        "Race": row.get("Race?", "").strip() or None,
        "Expression": map_expression(row.get("Expression?", "").strip()),
        "Obstruction": map_obstruction(row.get("Obstruction?", "").strip()),
        "Groups": map_group(row.get("Group?", "").strip()),
    }

def is_locked(s3, bucket, name, ext):
    lock_key = f"Locks/{name}{ext}.lock"
    try:
        s3.head_object(Bucket=bucket, Key=lock_key)
        return True
    except s3.exceptions.ClientError:
        return False

def rebalance(s3, bucket, csv_file, tolerance):
    print("[REBALANCE] Starting rebalance…")
    counts = build_current_counts(s3, bucket)
    print("[REBALANCE] Initial counts built.")

    # Load CSV (skip first line), and build image/video label map
    label_map = {"Images": {}, "Videos": {}}
    with open(csv_file, newline="", encoding="utf-8") as f:
        next(f)  # skip title
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Image Name"].strip()
            media = row["Image/Video"].strip()
            cloaked = row.get("Cloaking?", "").strip().lower() == "yes"
            if cloaked:
                continue  # skip cloaked
            media_type = "Images" if media.lower() == "image" else "Videos"
            label_map[media_type][name] = parse_labels(row)

    def compute_ratios(counts, media_type):
        ratios = []
        total = sum(counts[media_type][cat][val] for cat in counts[media_type] for val in counts[media_type][cat])
        total_needed = sum(DATASET_REQUIREMENTS[media_type][cat][val] for cat in DATASET_REQUIREMENTS[media_type] for val in DATASET_REQUIREMENTS[media_type][cat])
        average = total / total_needed if total_needed else 1
        all_ratios = []
        for cat in DATASET_REQUIREMENTS[media_type]:
            for val in DATASET_REQUIREMENTS[media_type][cat]:
                current = counts[media_type][cat].get(val, 0)
                needed = DATASET_REQUIREMENTS[media_type][cat][val]
                ratio = current / needed
                all_ratios.append((cat, val, ratio))
        return average, all_ratios

    for media_type in ["Images", "Videos"]:
        print(f"[REBALANCE] Processing {media_type}…")
        while True:
            average, ratios = compute_ratios(counts, media_type)
            low = [(cat, val, r) for (cat, val, r) in ratios if r < average - tolerance]
            high = [(cat, val, r) for (cat, val, r) in ratios if r > average + tolerance]
            if not low or not high:
                print(f"[REBALANCE] {media_type} balanced within tolerance.")
                break

            moved_any = False
            for cat_lo, val_lo, _ in sorted(low, key=lambda x: x[2]):
                for cat_hi, val_hi, _ in sorted(high, key=lambda x: -x[2]):
                    # search all files with both labels
                    for name, labels in label_map[media_type].items():
                        if labels.get(cat_lo) != val_lo or labels.get(cat_hi) != val_hi:
                            continue
                        ext = ".jpg" if media_type == "Images" else ".mp4"
                        key_old = f"Dataset/Uncloaked/{media_type}/{cat_hi}/{val_hi}/{name}{ext}"
                        key_new = f"Dataset/Uncloaked/{media_type}/{cat_lo}/{val_lo}/{name}{ext}"

                        if is_locked(s3, bucket, name, ext):
                            continue
                        try:
                            s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key_old}, Key=key_new)
                            s3.delete_object(Bucket=bucket, Key=key_old)
                            # Move cloaked files
                            for level in ("low", "mid", "high"):
                                cloaked_ext = ".png" if media_type == "Images" else ".mp4"
                                cloaked_name = f"{name}_cloaked_{level}{cloaked_ext}"
                                cloaked_old = f"Dataset/Cloaked/{media_type}/{cat_hi}/{val_hi}/{cloaked_name}"
                                cloaked_new = f"Dataset/Cloaked/{media_type}/{cat_lo}/{val_lo}/{cloaked_name}"
                                try:
                                    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": cloaked_old}, Key=cloaked_new)
                                    s3.delete_object(Bucket=bucket, Key=cloaked_old)
                                except s3.exceptions.ClientError:
                                    continue  # file might not exist
                            counts[media_type][cat_lo][val_lo] += 1
                            counts[media_type][cat_hi][val_hi] -= 1
                            moved_any = True
                            print(f"[REBALANCE] Moved {name}{ext} from {cat_hi}/{val_hi} → {cat_lo}/{val_lo}")
                            break
                        except s3.exceptions.ClientError as e:
                            print(f"[WARN] Failed to move {name}{ext}: {e}")
                            continue
                    if moved_any:
                        break
                if moved_any:
                    break
            if not moved_any:
                print(f"[REBALANCE] No eligible moves found for {media_type}. Stopping.")
                break

# -------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser("bucket_uploader.py")
    p.add_argument("--bucket-name", required=True)
    p.add_argument("--csv", help="CSV file (skip first 2 lines)")
    p.add_argument("--data", help="Folder with <name>.jpg/.mp4")
    p.add_argument("--reset", action="store_true", help="Delete all .jpg/.mp4 under Dataset/ in the bucket and exit")
    p.add_argument("--rebalance", action="store_true", help="Rebalance dataset distribution")
    p.add_argument("--info", action="store_true", help="Display dataset status information")
    p.add_argument("--tolerance", type=float, default=0.1, help="Rebalance tolerance (default 0.1)")
    args = p.parse_args()

    s3 = boto3.client("s3")
    bucket = args.bucket_name

    if args.reset:
        wipe_dataset(s3, bucket)
        sys.exit(0)

    if args.info:
        print_dataset_info(s3, bucket)
        sys.exit(0)

    if args.rebalance:
        if not args.csv:
            print("[ERROR] --csv is required for rebalancing", file=sys.stderr)
            sys.exit(1)
        rebalance(s3, bucket, args.csv, args.tolerance)
        sys.exit(0)

    if not args.csv or not args.data:
        print("[ERROR] --csv and --data are required", file=sys.stderr)
        sys.exit(1)

    print("Building counts from S3...")
    counts = build_current_counts(s3, bucket)
    print("Current counts:", counts)

    with open(args.csv, newline="", encoding="utf-8") as f:
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

            labels = parse_labels(row)
            type_plural = "Images" if media.lower() == "image" else "Videos"
            clr = "Uncloaked"

            cat, val = pick_target_folder(counts, type_plural, labels)
            if cat is None:
                print(f"[ERROR] no valid category for {name}, skipping", file=sys.stderr)
                continue

            key_prefix = f"Dataset/{clr}/{type_plural}/{cat}/{val}/"
            key = key_prefix + os.path.basename(local_path)

            s3.upload_file(local_path, bucket, key)
            counts[type_plural][cat][val] += 1

            print(f"Uploaded {name + ext} → s3://{bucket}/{key}")

if __name__ == "__main__":
    main()
