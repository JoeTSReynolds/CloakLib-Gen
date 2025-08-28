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

def reset_cloaked_level(s3, bucket, level):
    """Delete all cloaked files of a specific level (low, mid, high)"""
    if level not in ("low", "mid", "high"):
        print(f"[ERROR] Invalid level '{level}'. Must be one of: low, mid, high")
        return
    
    paginator = s3.get_paginator("list_objects_v2")
    print(f"[RESET-LEVEL] Deleting all cloaked '{level}' files from s3://{bucket}/Dataset/Cloaked/ …")
    
    to_delete = []
    deleted_count = 0
    
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Cloaked/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = os.path.basename(key)
            
            # Check if this is a cloaked file of the specified level
            # Expected format: name_cloaked_level.ext
            if f"_cloaked_{level}." in filename and key.lower().endswith((".jpg", ".png", ".mp4")):
                to_delete.append({"Key": key})
                
                # Delete in batches of 1000
                if len(to_delete) == 1000:
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
                    deleted_count += len(to_delete)
                    print(f"[RESET-LEVEL] Deleted {deleted_count} files so far...")
                    to_delete = []
    
    # Delete remaining files
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
        deleted_count += len(to_delete)
    
    print(f"[RESET-LEVEL] Done. Deleted {deleted_count} cloaked '{level}' files.")

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


def build_label_map_from_s3(s3, bucket):
    """Build label map from S3 bucket structure instead of CSV"""
    label_map = {"Images": {}, "Videos": {}}
    paginator = s3.get_paginator("list_objects_v2")
    
    # Pattern to extract media type, category, value, and filename from S3 keys
    pattern = re.compile(
        r"^Dataset/Uncloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"([^/]+)$"
    )
    
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Uncloaked/"):
        for obj in page.get("Contents", []):
            m = pattern.match(obj["Key"])
            if not m:
                continue
            
            media_type, category, value, filename = m.groups()
            
            # Extract base name (remove extension)
            name = os.path.splitext(filename)[0]
            
            # Initialize labels dict if not exists
            if name not in label_map[media_type]:
                label_map[media_type][name] = {}
            
            # Store the category-value pair for this file
            label_map[media_type][name][category] = value
    
    return label_map

def find_duplicates(s3, bucket):
    """Find duplicate filenames across all folders in the dataset"""
    duplicates = {"Images": defaultdict(list), "Videos": defaultdict(list)}
    paginator = s3.get_paginator("list_objects_v2")
    
    # Pattern to extract media type, category, value, and filename from S3 keys
    pattern = re.compile(
        r"^Dataset/Uncloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"([^/]+)$"
    )
    
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Uncloaked/"):
        for obj in page.get("Contents", []):
            m = pattern.match(obj["Key"])
            if not m:
                continue
            
            media_type, category, value, filename = m.groups()
            
            # Store the full S3 key info for each file
            file_info = {
                "key": obj["Key"],
                "category": category,
                "value": value,
                "filename": filename,
                "size": obj["Size"]
            }
            
            duplicates[media_type][filename].append(file_info)
    
    # Filter to only actual duplicates (files with same name in multiple locations)
    actual_duplicates = {"Images": {}, "Videos": {}}
    for media_type in duplicates:
        for filename, locations in duplicates[media_type].items():
            if len(locations) > 1:
                actual_duplicates[media_type][filename] = locations
    
    return actual_duplicates

def clean_duplicates(s3, bucket):
    """Clean duplicate files, keeping only one copy in the best location"""
    print("[CLEAN-DUPLICATES] Finding duplicates...")
    duplicates = find_duplicates(s3, bucket)
    
    total_duplicates = sum(len(files) for files in duplicates["Images"].values()) + \
                      sum(len(files) for files in duplicates["Videos"].values())
    
    if total_duplicates == 0:
        print("[CLEAN-DUPLICATES] No duplicates found.")
        return
    
    print(f"[CLEAN-DUPLICATES] Found {total_duplicates} duplicate file groups to process...")
    
    # Get current counts to make informed decisions about which copy to keep
    counts = build_current_counts(s3, bucket)
    
    files_deleted = 0
    
    for media_type in ["Images", "Videos"]:
        for filename, locations in duplicates[media_type].items():
            print(f"\n[CLEAN-DUPLICATES] Processing duplicate: {filename}")
            print(f"  Found in {len(locations)} locations:")
            for loc in locations:
                print(f"    - {loc['category']}/{loc['value']}")
            
            # Determine which copy to keep based on dataset balance
            best_location = None
            best_ratio = float('inf')
            
            for loc in locations:
                category = loc['category']
                value = loc['value']
                
                # Check if this category/value is in requirements
                if (category in DATASET_REQUIREMENTS[media_type] and 
                    value in DATASET_REQUIREMENTS[media_type][category]):
                    
                    current_count = counts[media_type][category].get(value, 0)
                    required_count = DATASET_REQUIREMENTS[media_type][category][value]
                    ratio = current_count / required_count
                    
                    # Prefer locations that are most under-represented
                    if ratio < best_ratio:
                        best_ratio = ratio
                        best_location = loc
                
                # If no valid requirements match, keep the first one
                if best_location is None:
                    best_location = loc
            
            print(f"  Keeping copy in: {best_location['category']}/{best_location['value']}")
            
            # Delete all other copies
            for loc in locations:
                if loc == best_location:
                    continue
                
                # Check if file is locked
                base_name = os.path.splitext(filename)[0]
                ext = os.path.splitext(filename)[1]
                if is_locked(s3, bucket, base_name, ext):
                    print(f"  Skipping locked file: {loc['key']}")
                    continue
                
                try:
                    # Delete the uncloaked file
                    s3.delete_object(Bucket=bucket, Key=loc['key'])
                    print(f"  Deleted: {loc['key']}")
                    files_deleted += 1
                    
                    # Also delete corresponding cloaked files if they exist
                    cloaked_deleted = 0
                    for level in ("low", "mid", "high"):
                        cloaked_ext = ".png" if media_type == "Images" else ".mp4"
                        cloaked_name = f"{base_name}_cloaked_{level}{cloaked_ext}"
                        cloaked_key = f"Dataset/Cloaked/{media_type}/{loc['category']}/{loc['value']}/{cloaked_name}"
                        
                        try:
                            s3.delete_object(Bucket=bucket, Key=cloaked_key)
                            print(f"    Deleted cloaked: {cloaked_key}")
                            cloaked_deleted += 1
                        except s3.exceptions.ClientError as e:
                            if e.response['Error']['Code'] != 'NoSuchKey':
                                print(f"    Warning: Failed to delete cloaked file {cloaked_key}: {e}")
                    
                    if cloaked_deleted > 0:
                        print(f"    Deleted {cloaked_deleted} cloaked versions")
                
                except s3.exceptions.ClientError as e:
                    print(f"  Error deleting {loc['key']}: {e}")
            
            # Update counts for the location we kept
            counts[media_type][best_location['category']][best_location['value']] -= (len(locations) - 1)
    
    print(f"\n[CLEAN-DUPLICATES] Cleanup complete. Deleted {files_deleted} duplicate files.")
    print("[CLEAN-DUPLICATES] Updated dataset counts after cleanup.")
    
    # Print final status
    print_dataset_info(s3, bucket)

def check_dataset_health(s3, bucket):
    """Check dataset health and report discrepancies"""
    print("[HEALTH] Checking dataset health...")
    
    # Build sets of uncloaked files
    uncloaked_files = {"Images": set(), "Videos": set()}
    paginator = s3.get_paginator("list_objects_v2")
    
    # Pattern to extract media type, category, value, and filename from uncloaked S3 keys
    uncloaked_pattern = re.compile(
        r"^Dataset/Uncloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"([^/]+)$"
    )
    
    print("[HEALTH] Scanning uncloaked files...")
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Uncloaked/"):
        for obj in page.get("Contents", []):
            m = uncloaked_pattern.match(obj["Key"])
            if not m:
                continue
            
            media_type, category, value, filename = m.groups()
            base_name = os.path.splitext(filename)[0]
            
            # Store the base name with its location info
            uncloaked_files[media_type].add((base_name, category, value))
    
    print(f"[HEALTH] Found {len(uncloaked_files['Images'])} uncloaked images and {len(uncloaked_files['Videos'])} uncloaked videos")
    
    # Now check cloaked files for orphans
    cloaked_pattern = re.compile(
        r"^Dataset/Cloaked/"
        r"(Images|Videos)/"
        r"([^/]+)/"
        r"([^/]+)/"
        r"([^/]+)$"
    )
    
    orphaned_cloaked = {"Images": [], "Videos": []}
    total_cloaked = {"Images": 0, "Videos": 0}
    
    print("[HEALTH] Scanning cloaked files...")
    for page in paginator.paginate(Bucket=bucket, Prefix="Dataset/Cloaked/"):
        for obj in page.get("Contents", []):
            m = cloaked_pattern.match(obj["Key"])
            if not m:
                continue
            
            media_type, category, value, filename = m.groups()
            total_cloaked[media_type] += 1
            
            # Extract base name from cloaked filename (remove _cloaked_level.ext)
            # Expected format: name_cloaked_level.ext
            base_name = filename
            if "_cloaked_" in filename:
                base_name = filename.split("_cloaked_")[0]
            else:
                # Fallback: just remove extension
                base_name = os.path.splitext(filename)[0]
            
            # Check if corresponding uncloaked file exists
            if (base_name, category, value) not in uncloaked_files[media_type]:
                orphaned_cloaked[media_type].append({
                    "key": obj["Key"],
                    "base_name": base_name,
                    "category": category,
                    "value": value,
                    "filename": filename
                })
    
    # Report results
    print("\n" + "="*80)
    print("DATASET HEALTH REPORT")
    print("="*80)
    
    total_orphans = len(orphaned_cloaked["Images"]) + len(orphaned_cloaked["Videos"])
    
    if total_orphans == 0:
        print("✅ DATASET HEALTH: GOOD")
        print("   No orphaned cloaked files found.")
    else:
        print("⚠️  DATASET HEALTH: ISSUES DETECTED")
        print(f"   Found {total_orphans} orphaned cloaked files.")
    
    for media_type in ["Images", "Videos"]:
        print(f"\n{media_type.upper()}:")
        print(f"  Total cloaked files: {total_cloaked[media_type]}")
        print(f"  Orphaned cloaked files: {len(orphaned_cloaked[media_type])}")
        
        if orphaned_cloaked[media_type]:
            print("  Orphaned files:")
            for orphan in orphaned_cloaked[media_type][:10]:  # Show first 10
                print(f"    - {orphan['key']}")
                print(f"      Missing uncloaked: Dataset/Uncloaked/{media_type}/{orphan['category']}/{orphan['value']}/{orphan['base_name']}.{'jpg' if media_type == 'Images' else 'mp4'}")
            
            if len(orphaned_cloaked[media_type]) > 10:
                print(f"    ... and {len(orphaned_cloaked[media_type]) - 10} more")
    
    print("\n" + "="*80)
    
    if total_orphans > 0:
        print("\nRECOMMENDATIONS:")
        print("- Review the orphaned cloaked files listed above")
        print("- These files may be consuming storage space unnecessarily")
        print("- Consider removing orphaned files if they're no longer needed")
        print("- Check if the original uncloaked files were accidentally deleted")
    
    return {
        "total_orphans": total_orphans,
        "orphaned_files": orphaned_cloaked,
        "total_cloaked": total_cloaked
    }

def rebalance(s3, bucket, csv_file, tolerance):
    print("[REBALANCE] Starting rebalance…")
    counts = None
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
            counts = build_current_counts(s3, bucket)
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
                            if e.response['Error']['Code'] == 'NoSuchKey':
                                continue
                            print(f"[WARN] Failed to move {name}{ext}: {e}")
                            continue
                    if moved_any:
                        break
                if moved_any:
                    break
            if not moved_any:
                print(f"[REBALANCE] No more eligible moves found for {media_type}. Stopping.")
                break

# -------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser("bucket_uploader.py")
    p.add_argument("--bucket-name", required=True)
    p.add_argument("--csv", help="CSV file (skip first 2 lines)")
    p.add_argument("--data", help="Folder with <name>.jpg/.mp4")
    p.add_argument("--reset", action="store_true", help="Delete all .jpg/.mp4 under Dataset/ in the bucket and exit")
    p.add_argument("--reset-level", choices=["low", "mid", "high"], help="Delete all cloaked files of a specific level (low, mid, high)")
    p.add_argument("--rebalance", action="store_true", help="Rebalance dataset distribution")
    p.add_argument("--info", action="store_true", help="Display dataset status information")
    p.add_argument("--clean-duplicates", action="store_true", help="Remove duplicate filenames, keeping only one copy in the most balanced location")
    p.add_argument("--health", action="store_true", help="Check dataset health and report discrepancies")
    p.add_argument("--tolerance", type=float, default=0.1, help="Rebalance tolerance (default 0.1)")
    args = p.parse_args()

    s3 = boto3.client("s3", region_name="eu-west-2")
    bucket = args.bucket_name

    if args.reset:
        wipe_dataset(s3, bucket)
        sys.exit(0)

    if args.reset_level:
        reset_cloaked_level(s3, bucket, args.reset_level)
        sys.exit(0)

    if args.info:
        print_dataset_info(s3, bucket)
        sys.exit(0)

    if args.health:
        check_dataset_health(s3, bucket)
        sys.exit(0)

    if args.clean_duplicates:
        clean_duplicates(s3, bucket)
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
