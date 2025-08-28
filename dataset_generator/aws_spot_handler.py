import boto3
import json
import os
import signal
import sys
import threading
import glob
from urllib.request import urlopen
from urllib.error import URLError
import urllib
from datetime import datetime, timezone
from tqdm import tqdm
import cv2
import re
from cloaklib import CloakingLibrary

def get_timestamp():
    """Get current timestamp in formatted string"""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

class SpotInterruptHandler:
    """Handles AWS spot instance interruption gracefully"""
    
    def __init__(self, s3_client, bucket_name, cleanup_callback=None, s3_handler_ref=None):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.cleanup_callback = cleanup_callback
        self.s3_handler_ref = s3_handler_ref  # optional reference to handler for pending lock cleanup
        self.interrupted = False
        self.current_lock_key = None
        self.monitoring_thread = None
        self.stop_monitoring = threading.Event()
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._handle_interrupt)
        signal.signal(signal.SIGINT, self._handle_interrupt)
    
    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signals"""
        print(f"{get_timestamp()} Received interrupt signal {signum}. Starting graceful shutdown...")
        self.interrupted = True
        self.stop_monitoring.set()
        # Release current lock first to avoid double-delete after bulk cleanup
        self._release_current_lock()
        if self.cleanup_callback:
            self.cleanup_callback()
        sys.exit(0)
    
    def start_monitoring(self):
        """Start monitoring for spot instance interruption"""
        self.monitoring_thread = threading.Thread(target=self._monitor_spot_interruption)
        self.monitoring_thread.daemon = True
        self.monitoring_thread.start()
        print(f"{get_timestamp()} Started spot instance interruption monitoring...")
    
    def _monitor_spot_interruption(self):
        """Monitor AWS metadata for spot interruption notice"""
        metadata_url = "http://169.254.169.254/latest/meta-data/spot/instance-action"
        
        # Get IMDSv2 token first
        token_url = "http://169.254.169.254/latest/api/token"
        
        while not self.stop_monitoring.is_set():
            try:
                # Get token for IMDSv2
                token_request = urllib.request.Request(
                    token_url,
                    headers={'X-aws-ec2-metadata-token-ttl-seconds': '21600'},
                    method='PUT'
                )
                with urlopen(token_request, timeout=2) as token_response:
                    token = token_response.read().decode('utf-8')
                
                # Check for interruption with token
                interruption_request = urllib.request.Request(
                    metadata_url,
                    headers={'X-aws-ec2-metadata-token': token}
                )
                
                with urlopen(interruption_request, timeout=2) as response:
                    if response.getcode() == 200:
                        interruption_data = response.read().decode('utf-8')
                        print(f"\n*** SPOT INSTANCE INTERRUPTION DETECTED ***")
                        print(f"Interruption details: {interruption_data}")
                        print("Initiating graceful shutdown...")
                        self._handle_interrupt(signal.SIGTERM, None)
                        break
                        
            except URLError as e:
                if hasattr(e, 'code') and e.code == 404:
                    # No interruption notice - this is normal
                    pass
                else:
                    print(f"Error checking spot interruption: {e}")
            except Exception as e:
                print(f"Error checking spot interruption: {e}")
            
            # Check every 30 seconds
            self.stop_monitoring.wait(30)
        
    def set_current_lock(self, lock_key):
        """Set the current file lock being processed"""
        self.current_lock_key = lock_key
    
    def _release_current_lock(self):
        """Release the current file lock"""
        if self.current_lock_key:
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=self.current_lock_key)
                # Remove from pending set if present
                if self.s3_handler_ref and self.current_lock_key in self.s3_handler_ref.pending_locks:
                    self.s3_handler_ref.pending_locks.discard(self.current_lock_key)
                print(f"Released lock: {self.current_lock_key} (current)")
            except Exception as e:
                print(f"Error releasing lock {self.current_lock_key}: {e}")
            self.current_lock_key = None


class AWSS3Handler:
    """Handles AWS S3 operations for the cloaking dataset"""
    
    def __init__(self, bucket_name, aws_region='eu-west-2'):
        self.bucket_name = bucket_name
        self.aws_region = aws_region
        self.s3_client = boto3.client('s3', region_name=aws_region)

        # Directory structure in S3
        self.uncloaked_prefix = "Dataset/Uncloaked/"
        self.cloaked_prefix = "Dataset/Cloaked/"
        self.locks_prefix = "Locks/"
        self.temp_prefix = "Temp/"
        
        # Supported formats
        self.SUPPORTED_IMAGE_FORMATS = CloakingLibrary.SUPPORTED_IMAGE_FORMATS
        self.SUPPORTED_VIDEO_FORMATS = CloakingLibrary.SUPPORTED_VIDEO_FORMATS

        # Dataset requirements from CloakingLibrary
        self.dataset_requirements = CloakingLibrary.DATASET_REQUIREMENTS

        # ---------------- Local processed tracker (added) ----------------
        # Tracks which originals have which cloak levels already processed
        # to avoid repeated S3 HEAD checks across loop iterations.
        self._tracker_path = os.getenv('PROCESSED_TRACKER_PATH', '.processed_tracker.json')
        self._processed_tracker = self._load_processed_tracker()
        # Track all currently held (pre-acquired) lock object keys so we can
        # release them on interrupt before shutting down.
        self.pending_locks = set()
        # Perform one-time optional sync of local tracker (can be deferred to caller)

    # ---------------- Sync Existing Processed State ----------------
    def sync_local_tracker(self, force=False):
        """Populate local processed tracker by listing S3 once.
        Strategy (LIST-only, no HEAD):
          1. List all originals under uncloaked_prefix to build a mapping of (dir, base_name) -> (original_key, media_type)
          2. List all cloaked objects; parse filename pattern '<base>_cloaked_<level>.(png|mp4)'; map back to original using dir+base.
             For videos: only 'mid' counts toward completion per current policy.
        This runs once at startup unless force=True or tracker empty.
        """
        if self._processed_tracker['files'] and not force:
            return  # Already populated
        print("Syncing local processed tracker from S3...")
        mapping = {}  # (relative_dir, base_name) -> (original_key, media_type)
        paginator = self.s3_client.get_paginator('list_objects_v2')
        # Pass 1: originals
        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.uncloaked_prefix):
                if 'Contents' not in page:
                    continue
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.endswith('/'):
                        continue
                    rel_path = key[len(self.uncloaked_prefix):]
                    rel_dir = os.path.dirname(rel_path)
                    fname = os.path.basename(key)
                    base, ext = os.path.splitext(fname)
                    ext_l = ext.lower()
                    if ext_l in self.SUPPORTED_IMAGE_FORMATS:
                        media_type = 'image'
                    elif ext_l in self.SUPPORTED_VIDEO_FORMATS:
                        media_type = 'video'
                    else:
                        continue
                    mapping[(rel_dir, base)] = (key, media_type)
        except Exception as e:
            print(f"Error listing originals for sync: {e}")
        # Pass 2: cloaked
        cloaked_pattern = re.compile(r"^(?P<base>.+)_cloaked_(?P<level>low|mid|high)\.(png|mp4)$", re.IGNORECASE)
        counts = { 'image': 0, 'video': 0 }
        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.cloaked_prefix):
                if 'Contents' not in page:
                    continue
                for obj in page['Contents']:
                    ckey = obj['Key']
                    if ckey.endswith('/'):
                        continue
                    rel_path = ckey[len(self.cloaked_prefix):]
                    rel_dir = os.path.dirname(rel_path)
                    fname = os.path.basename(ckey)
                    m = cloaked_pattern.match(fname)
                    if not m:
                        continue
                    base = m.group('base')
                    level = m.group('level').lower()
                    map_entry = mapping.get((rel_dir, base))
                    if not map_entry:
                        continue  # Could be orphan or naming mismatch
                    original_key, media_type = map_entry
                    # For videos only record 'mid'; ignore others per policy
                    if media_type == 'video' and level != 'mid':
                        continue
                    self.mark_level_processed_local(original_key, level, media_type)
                    counts[media_type] += 1
        except Exception as e:
            print(f"Error listing cloaked for sync: {e}")
        # Finalize full-done flags for images
        for key, entry in self._processed_tracker['files'].items():
            if 'all_done' not in entry:
                if set(entry.get('processed_levels', [])) >= {'low','mid','high'}:
                    entry['all_done'] = True
                elif 'mid' in entry.get('processed_levels', []) and any(key.lower().endswith(ext) for ext in self.SUPPORTED_VIDEO_FORMATS):
                    entry['all_done'] = True
        self._save_processed_tracker()
        print(f"Sync complete. Tracker entries: {len(self._processed_tracker['files'])} (image levels recorded: {counts['image']}, video mids recorded: {counts['video']})")

    # ===================== Tracker Helpers =====================
    def _load_processed_tracker(self):
        try:
            if os.path.exists(self._tracker_path):
                with open(self._tracker_path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, dict) and 'files' in data:
                    return data
        except Exception as e:
            print(f"Warning: could not load processed tracker: {e}")
        return {'files': {}}  # schema: { files: { key: { processed_levels: [...], all_done: bool } } }

    def _save_processed_tracker(self):
        try:
            with open(self._tracker_path, 'w') as f:
                json.dump(self._processed_tracker, f, indent=2)
        except Exception as e:
            print(f"Warning: could not save processed tracker: {e}")

    def _get_tracker_entry(self, file_key):
        return self._processed_tracker['files'].setdefault(file_key, {'processed_levels': [], 'all_done': False})

    def mark_level_processed_local(self, file_key, level, media_type):
        entry = self._get_tracker_entry(file_key)
        if level not in entry['processed_levels']:
            entry['processed_levels'].append(level)
        # Images: complete when all three levels present.
        # Videos (policy change): only 'mid' level matters; treat as complete once mid processed.
        if media_type == 'video':
            if 'mid' in entry['processed_levels']:
                entry['all_done'] = True
        else:
            if set(entry['processed_levels']) >= {'low','mid','high'}:
                entry['all_done'] = True
        self._save_processed_tracker()

    def mark_all_levels_processed_local(self, file_key):
        entry = self._get_tracker_entry(file_key)
        entry['processed_levels'] = ['low','mid','high']
        entry['all_done'] = True
        self._save_processed_tracker()

    def already_has_level(self, file_key, level):
        entry = self._processed_tracker['files'].get(file_key)
        return entry and (level in entry.get('processed_levels', []))

    def is_fully_processed_local(self, file_key):
        entry = self._processed_tracker['files'].get(file_key)
        return bool(entry and entry.get('all_done'))

    # ===================== Queue / Candidate Logic =====================
    def build_processing_queue(self, desired_count=3, target_level='mid', all_levels=False):
        """Build a queue (list) of up to desired_count items to process.
        Each item: { 'file_key': str, 'lock_key': str, 'media_type': 'image'|'video' }
        We DO NOT perform HEAD checks here (per requirement). We create locks immediately.
        Skips entries fully processed according to local tracker.
        """
        queue = []
        # Iterate over Images then Videos or GPU preference? Simplicity: both prefixes via paginator
        # We'll reuse existing listing logic scanning uncloaked prefix once until queue filled.
        paginator = self.s3_client.get_paginator('list_objects_v2')
        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.uncloaked_prefix):
                if 'Contents' not in page:
                    continue
                for obj in page['Contents']:
                    if len(queue) >= desired_count:
                        return queue
                    key = obj['Key']
                    if key.endswith('/'):
                        continue
                    ext = os.path.splitext(key)[1].lower()
                    media_type = None
                    if ext in self.SUPPORTED_IMAGE_FORMATS:
                        media_type = 'image'
                    elif ext in self.SUPPORTED_VIDEO_FORMATS:
                        media_type = 'video'
                    else:
                        continue
                    # Skip if previously marked as failed
                    try:
                        if self._is_file_failed(key):
                            continue
                    except Exception:
                        pass
                    if media_type == 'video':
                        # Video policy: only process mid level ever. Skip if mid already done.
                        if self.already_has_level(key, 'mid') or (key in self._processed_tracker['files'] and 'mid' in self._processed_tracker['files'][key]['processed_levels']):
                            continue
                    else:
                        # Image logic remains: all levels when requested
                        if all_levels and self.is_fully_processed_local(key):
                            continue
                        if not all_levels and self.already_has_level(key, target_level):
                            continue
                    # Acquire lock now
                    lock_key = self.create_lock(os.path.basename(key))
                    if not lock_key:
                        continue  # some other instance locked it
                    self.pending_locks.add(lock_key)
                    queue.append({'file_key': key, 'lock_key': lock_key, 'media_type': media_type})
            return queue
        except Exception as e:
            print(f"Error building processing queue: {e}")
            return queue

    def determine_missing_levels(self, file_key):
        """Determine missing cloak levels using local tracker first then S3 HEAD only for unknown levels.
        Returns list of missing levels (subset of ['low','mid','high']).
        """
        file_name = os.path.basename(file_key)
        base_name, ext = os.path.splitext(file_name)
        ext_lower = ext.lower()
        entry = self._processed_tracker['files'].get(file_key)
        processed_levels = set(entry['processed_levels']) if entry else set()
        # Video: only mid counts
        if ext_lower in self.SUPPORTED_VIDEO_FORMATS:
            if 'mid' in processed_levels:
                return []
            # Need to check S3 once for mid if not locally recorded
            cloaked_ext = '.mp4'
            relative_path = file_key[len(self.uncloaked_prefix):]
            relative_dir = os.path.dirname(relative_path)
            cloaked_name = f"{base_name}_cloaked_mid{cloaked_ext}"
            if relative_dir:
                cloaked_key = f"{self.cloaked_prefix}{relative_dir}/{cloaked_name}"
            else:
                cloaked_key = f"{self.cloaked_prefix}{cloaked_name}"
            cloaked_key = cloaked_key.replace('\\','/').replace('//','/')
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=cloaked_key)
                self.mark_level_processed_local(file_key, 'mid', 'video')
                return []
            except self.s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    return ['mid']
                else:
                    print(f"Error HEAD {cloaked_key}: {e}")
                    return ['mid']
            except Exception as e:
                print(f"Error HEAD {cloaked_key}: {e}")
                return ['mid']
        # Image logic unchanged (all three potential levels)
        missing = []
        cloaked_ext = '.png' if ext_lower in self.SUPPORTED_IMAGE_FORMATS else None
        if cloaked_ext is None:
            return []
        for level in ['low','mid','high']:
            if level in processed_levels:
                continue
            relative_path = file_key[len(self.uncloaked_prefix):]
            relative_dir = os.path.dirname(relative_path)
            cloaked_name = f"{base_name}_cloaked_{level}{cloaked_ext}"
            if relative_dir:
                cloaked_key = f"{self.cloaked_prefix}{relative_dir}/{cloaked_name}"
            else:
                cloaked_key = f"{self.cloaked_prefix}{cloaked_name}"
            cloaked_key = cloaked_key.replace('\\','/').replace('//','/')
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=cloaked_key)
                self.mark_level_processed_local(file_key, level, 'image')
            except self.s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    missing.append(level)
                else:
                    print(f"Error HEAD {cloaked_key}: {e}")
                    missing.append(level)
            except Exception as e:
                print(f"Error HEAD {cloaked_key}: {e}")
                missing.append(level)
        # If all three recorded mark complete
        if file_key in self._processed_tracker['files'] and set(self._processed_tracker['files'][file_key]['processed_levels']) >= {'low','mid','high'}:
            self._processed_tracker['files'][file_key]['all_done'] = True
            self._save_processed_tracker()
        return missing
    
    def _has_gpu_available(self):
        """Check if GPU is available for processing"""
        try:
            import torch
            return torch.cuda.is_available() and torch.cuda.device_count() > 0
        except ImportError:
            # If torch is not available, try alternative methods
            try:
                import subprocess
                result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=5)
                return result.returncode == 0
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
                return False
        except Exception:
            return False
    
    def _separate_files_by_type(self, file_list):
        """Separate files into images and videos"""
        images = []
        videos = []
        
        for file_key in file_list:
            ext = os.path.splitext(file_key)[1].lower()
            if ext in self.SUPPORTED_IMAGE_FORMATS:
                images.append(file_key)
            elif ext in self.SUPPORTED_VIDEO_FORMATS:
                videos.append(file_key)
        
        return images, videos
    
    def list_files_in_prefix(self, prefix):
        """List all files in S3 with given prefix"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' in response:
                return [obj['Key'] for obj in response['Contents']]
            return []
        except Exception as e:
            print(f"Error listing files with prefix {prefix}: {e}")
            return []
    
    def create_dataset_folder_structure(self):
        """Create the complete folder structure in S3 based on DATASET_REQUIREMENTS"""
        print("Creating S3 folder structure based on DATASET_REQUIREMENTS...")
        
        folders_created = 0
        for media_type, categories in self.dataset_requirements.items():
            for category, subcategories in categories.items():
                for subcategory in subcategories.keys():
                    # Create folders for both uncloaked and cloaked
                    uncloaked_folder = f"{self.uncloaked_prefix}{media_type}/{category}/{subcategory}/"
                    cloaked_folder = f"{self.cloaked_prefix}{media_type}/{category}/{subcategory}/"
                    
                    for folder in [uncloaked_folder, cloaked_folder]:
                        try:
                            # Create a placeholder object to represent the folder
                            self.s3_client.put_object(
                                Bucket=self.bucket_name,
                                Key=folder,
                                Body=''
                            )
                            folders_created += 1
                        except Exception as e:
                            print(f"Error creating folder {folder}: {e}")
        
        print(f"Created {folders_created} folders in S3 bucket structure")
        return folders_created > 0
    
    def scan_all_subfolders_for_files(self):
        """Recursively scan all subfolders in the uncloaked directory for media files"""
        print("Scanning all subfolders for media files...")
        
        all_files = []
        
        # Get all objects under the uncloaked prefix
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=self.uncloaked_prefix
            )
            
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        file_key = obj['Key']
                        
                        # Skip directories (keys ending with '/')
                        if file_key.endswith('/'):
                            continue
                        
                        # Check if file has supported extension
                        ext = os.path.splitext(file_key)[1].lower()
                        if ext in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS:
                            all_files.append(file_key)
        
        except Exception as e:
            print(f"Error scanning subfolders: {e}")
            return []
        
        print(f"Found {len(all_files)} media files in all subfolders")
        return all_files
    
    def download_file(self, s3_key, local_path):
        """Download a file from S3"""
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            return True
        except Exception as e:
            print(f"Error downloading {s3_key}: {e}")
            return False
    
    def upload_file(self, local_path, s3_key):
        """Upload a file to S3"""
        try:
            self.s3_client.upload_file(local_path, self.bucket_name, s3_key)
            return True
        except Exception as e:
            print(f"Error uploading {local_path} to {s3_key}: {e}")
            return False
    
    def create_lock(self, file_name):
        """Create a processing lock for a file"""
        lock_key = f"{self.locks_prefix}{file_name}.lock"
        try:
            # Check if lock already exists
            self.s3_client.head_object(Bucket=self.bucket_name, Key=lock_key)
            return None  # Lock already exists
        except self.s3_client.exceptions.ClientError as e:
            if e.response['Error']['Code'] != '404':
                print(f"Error checking lock {lock_key}: {e}")
                return None
            # Lock doesn't exist, create it
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=lock_key,
                    Body=json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "instance_id": self._get_instance_id()
                    })
                )
                return lock_key
            except Exception as e:
                print(f"Error creating lock {lock_key}: {e}")
                return None
        except Exception as e:
            print(f"Error checking lock {lock_key}: {e}")
            return None
    
    def release_lock(self, lock_key):
        """Release a processing lock"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=lock_key)
            if lock_key in self.pending_locks:
                self.pending_locks.discard(lock_key)
            return True
        except Exception as e:
            print(f"Error releasing lock {lock_key}: {e}")
            return False

    def release_all_locks(self):
        """Release all currently pending locks (used on interrupt)."""
        for lk in list(self.pending_locks):
            self.release_lock(lk)
    
    def _get_instance_id(self):
        """Get the current EC2 instance ID"""
        try:
            response = urlopen("http://169.254.169.254/latest/meta-data/instance-id", timeout=2)
            return response.read().decode('utf-8')
        except:
            return "unknown"
    
    def get_next_file_to_process(self):
        """Find the next uncloaked file that needs processing from all subfolders
        Prioritizes videos if GPU is available, otherwise prioritizes images"""
        
        has_gpu = self._has_gpu_available()
        
        if has_gpu:
            print(f"{get_timestamp()} GPU detected. Looking for videos first, then images...")
            # Try videos first
            result = self._find_next_unprocessed_file_in_directory("Videos")
            if result[0] is not None:
                return result[0], result[1]
            # Fall back to images
            result = self._find_next_unprocessed_file_in_directory("Images")
            return result[0], result[1]
        else:
            print(f"{get_timestamp()} No GPU detected. Looking for images first, then videos...")
            # Try images first
            result = self._find_next_unprocessed_file_in_directory("Images")
            if result[0] is not None:
                return result[0], result[1]
            # Fall back to videos if only videos left
            print(f"{get_timestamp()} No images available, checking for videos...")
            result = self._find_next_unprocessed_file_in_directory("Videos")
            return result[0], result[1]
    
    def _is_already_processed(self, uncloaked_file_key):
        """Check if a file has already been processed (has cloaked versions)"""
        # Extract the base name and construct expected cloaked file paths
        file_name = os.path.basename(uncloaked_file_key)
        base_name, ext = os.path.splitext(file_name)

        if ext.lower() in self.SUPPORTED_IMAGE_FORMATS:
            ext = '.png'  # Normalize to PNG for cloaked images

        elif ext.lower() in self.SUPPORTED_VIDEO_FORMATS:
            ext = '.mp4'
        
        # Get the relative path from the uncloaked prefix
        relative_path = uncloaked_file_key[len(self.uncloaked_prefix):]
        relative_dir = os.path.dirname(relative_path)
        
        # Check for cloaked versions with different levels
        for level in ['low', 'mid', 'high']:
            cloaked_name = f"{base_name}_cloaked_{level}{ext}"
            
            # Construct the expected S3 path for cloaked file
            if relative_dir:
                cloaked_key = f"{self.cloaked_prefix}{relative_dir}/{cloaked_name}"
            else:
                cloaked_key = f"{self.cloaked_prefix}{cloaked_name}"
            
            # Normalize path separators
            cloaked_key = cloaked_key.replace("\\", "/").replace("//", "/")
            
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=cloaked_key)
                return True  # Found at least one cloaked version
            except self.s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    continue
                else:
                    print(f"Error checking for cloaked file {cloaked_key}: {e}")
                    continue

        return False
    
    def get_next_file_to_process_all_levels(self):
        """Find the next uncloaked file that needs processing in any missing protection level
        Prioritizes videos if GPU is available, otherwise prioritizes images"""
        
        has_gpu = self._has_gpu_available()
        
        if has_gpu:
            print(f"{get_timestamp()} GPU detected. Looking for videos first, then images...")
            # Try videos first
            result = self._find_next_file_in_directory("Videos")
            if result[0] is not None:
                return result
            # Fall back to images
            result = self._find_next_file_in_directory("Images") 
            return result
        else:
            print(f"{get_timestamp()} No GPU detected. Looking for images first, then videos...")
            # Try images first
            result = self._find_next_file_in_directory("Images")
            if result[0] is not None:
                return result
            # Fall back to videos if only videos left
            print(f"{get_timestamp()} No images available, checking for videos...")
            result = self._find_next_file_in_directory("Videos")
            return result
    
    def _find_next_unprocessed_file_in_directory(self, media_type):
        """Efficiently find the next completely unprocessed file in a specific media type directory"""
        search_prefix = f"{self.uncloaked_prefix}{media_type}/"
        
        try:
            # Use paginator to efficiently scan through files
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=search_prefix
            )
            
            for page in page_iterator:
                if 'Contents' not in page:
                    continue
                    
                for obj in page['Contents']:
                    file_key = obj['Key']
                    
                    # Skip directories (keys ending with '/')
                    if file_key.endswith('/'):
                        continue
                    
                    # Check if file has supported extension
                    ext = os.path.splitext(file_key)[1].lower()
                    expected_formats = self.SUPPORTED_VIDEO_FORMATS if media_type == "Videos" else self.SUPPORTED_IMAGE_FORMATS
                    
                    if ext not in expected_formats:
                        continue
                    
                    # Quick check: is this file failed?
                    if self._is_file_failed(file_key):
                        continue
                    
                    # Check if completely unprocessed
                    if self._is_already_processed(file_key):
                        continue
                    
                    # Try to create a lock for this file
                    file_name = os.path.basename(file_key)
                    lock_key = self.create_lock(file_name)
                    if lock_key:
                        print(f"{get_timestamp()} Selected {media_type.lower()[:-1]}: {file_key}")
                        return file_key, lock_key
                    
                    # If we can't lock this file, continue to the next one
                    continue
        
        except Exception as e:
            print(f"Error searching {media_type} directory: {e}")
        
        return None, None

    def _find_next_file_in_directory(self, media_type):
        """Efficiently find the next file to process in a specific media type directory (Images or Videos)"""
        search_prefix = f"{self.uncloaked_prefix}{media_type}/"
        
        try:
            # Use paginator to efficiently scan through files
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=search_prefix
            )
            
            for page in page_iterator:
                if 'Contents' not in page:
                    continue
                    
                for obj in page['Contents']:
                    file_key = obj['Key']
                    
                    # Skip directories (keys ending with '/')
                    if file_key.endswith('/'):
                        continue
                    
                    # Check if file has supported extension
                    ext = os.path.splitext(file_key)[1].lower()
                    expected_formats = self.SUPPORTED_VIDEO_FORMATS if media_type == "Videos" else self.SUPPORTED_IMAGE_FORMATS
                    
                    if ext not in expected_formats:
                        continue
                    
                    # Quick check: is this file failed?
                    if self._is_file_failed(file_key):
                        continue
                    
                    # Check for missing cloak levels
                    missing_levels = self._get_missing_cloak_levels(file_key)
                    if not missing_levels:
                        continue  # Already fully processed
                    
                    # Try to create a lock for this file
                    file_name = os.path.basename(file_key)
                    lock_key = self.create_lock(file_name)
                    if lock_key:
                        print(f"{get_timestamp()} Selected {media_type.lower()[:-1]}: {file_key} (missing levels: {missing_levels})")
                        return file_key, lock_key, missing_levels
                    
                    # If we can't lock this file, continue to the next one
                    continue
        
        except Exception as e:
            print(f"Error searching {media_type} directory: {e}")
        
        return None, None, []

    def _get_missing_cloak_levels(self, uncloaked_file_key):
        """Check which cloak levels are missing for a file"""
        file_name = os.path.basename(uncloaked_file_key)
        base_name, ext = os.path.splitext(file_name)

        if ext.lower() in self.SUPPORTED_IMAGE_FORMATS:
            ext = '.png'  # Normalize to PNG for cloaked images
        elif ext.lower() in self.SUPPORTED_VIDEO_FORMATS:
            ext = '.mp4'
        
        # Get the relative path from the uncloaked prefix
        relative_path = uncloaked_file_key[len(self.uncloaked_prefix):]
        relative_dir = os.path.dirname(relative_path)
        
        missing_levels = []
        
        # Check for each cloak level
        for level in ['low', 'mid', 'high']:
            cloaked_name = f"{base_name}_cloaked_{level}{ext}"
            
            # Construct the expected S3 path for cloaked file
            if relative_dir:
                cloaked_key = f"{self.cloaked_prefix}{relative_dir}/{cloaked_name}"
            else:
                cloaked_key = f"{self.cloaked_prefix}{cloaked_name}"
            
            # Normalize path separators
            cloaked_key = cloaked_key.replace("\\", "/").replace("//", "/")
            
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=cloaked_key)
                # File exists, this level is already processed
                continue
            except self.s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    # File doesn't exist, this level is missing
                    missing_levels.append(level)
                else:
                    print(f"Error checking for cloaked file {cloaked_key}: {e}")
                    continue
        
        return missing_levels
    
    def save_temp_video_progress(self, original_file_key, progress_data):
        """Save temporary video processing progress to S3"""
        file_name = os.path.basename(original_file_key)
        base_name = os.path.splitext(file_name)[0]
        
        temp_key = f"{self.temp_prefix}{base_name}_progress.json"
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=temp_key,
                Body=json.dumps(progress_data, indent=2)
            )
            return temp_key
        except Exception as e:
            print(f"Error saving temp progress: {e}")
            return None
    
    def load_temp_video_progress(self, original_file_key):
        """Load temporary video processing progress from S3"""
        file_name = os.path.basename(original_file_key)
        base_name = os.path.splitext(file_name)[0]
        
        temp_key = f"{self.temp_prefix}{base_name}_progress.json"
        
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=temp_key)
            return json.loads(response['Body'].read().decode('utf-8'))
        except self.s3_client.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            else:
                print(f"Error loading temp progress {temp_key}: {e}")
                return None
        except Exception as e:
            print(f"Error loading temp progress {temp_key}: {e}")
            return None
    
    def upload_temp_frames(self, local_frames_dir, original_file_key):
        """Upload temporary processed frames to S3"""
        file_name = os.path.basename(original_file_key)
        base_name = os.path.splitext(file_name)[0]
        
        frame_keys = []
        frame_files = sorted(glob.glob(os.path.join(local_frames_dir, "frame_*.png")))
        
        for frame_file in tqdm(frame_files, desc="Uploading temp frames"):
            frame_name = os.path.basename(frame_file)
            temp_frame_key = f"{self.temp_prefix}{base_name}_frames/{frame_name}"
            
            if self.upload_file(frame_file, temp_frame_key):
                frame_keys.append(temp_frame_key)
        
        return frame_keys
    
    def download_temp_frames(self, original_file_key, local_frames_dir):
        """Download temporary processed frames from S3"""
        file_name = os.path.basename(original_file_key)
        base_name = os.path.splitext(file_name)[0]
        
        os.makedirs(local_frames_dir, exist_ok=True)
        
        # List all temp frames for this video
        temp_frames_prefix = f"{self.temp_prefix}{base_name}_frames/"
        frame_keys = self.list_files_in_prefix(temp_frames_prefix)
        
        downloaded_frames = []
        for frame_key in tqdm(frame_keys, desc="Downloading temp frames"):
            frame_name = os.path.basename(frame_key)
            local_frame_path = os.path.join(local_frames_dir, frame_name)
            
            if self.download_file(frame_key, local_frame_path):
                downloaded_frames.append(local_frame_path)
        
        return sorted(downloaded_frames)
    
    def cleanup_temp_files(self, original_file_key):
        """Clean up temporary files for a processed video"""
        file_name = os.path.basename(original_file_key)
        base_name = os.path.splitext(file_name)[0]
        
        # Clean up progress file
        progress_key = f"{self.temp_prefix}{base_name}_progress.json"
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=progress_key)
        except:
            pass
        
        # Clean up temp frames
        temp_frames_prefix = f"{self.temp_prefix}{base_name}_frames/"
        frame_keys = self.list_files_in_prefix(temp_frames_prefix)
        
        for frame_key in frame_keys:
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=frame_key)
            except:
                pass
    
    def upload_processed_file(self, local_file_path, original_s3_key, cloak_level):
        """Upload a processed (cloaked) file to the appropriate S3 location"""
        # Extract file info
        file_name = os.path.basename(original_s3_key)
        base_name, ext = os.path.splitext(file_name)

        if ext.lower() in self.SUPPORTED_IMAGE_FORMATS:
            ext = '.png'  # Normalize to PNG for cloaked images

        elif ext.lower() in self.SUPPORTED_VIDEO_FORMATS:
            ext = '.mp4'
        
        # Create cloaked filename
        cloaked_name = f"{base_name}_cloaked_{cloak_level}{ext}"
        
        # Get the relative path from the uncloaked prefix
        relative_path = original_s3_key[len(self.uncloaked_prefix):]
        relative_dir = os.path.dirname(relative_path)
        
        # Construct cloaked S3 path (mirror directory structure)
        if relative_dir:
            cloaked_key = f"{self.cloaked_prefix}{relative_dir}/{cloaked_name}"
        else:
            cloaked_key = f"{self.cloaked_prefix}{cloaked_name}"
        
        # Normalize path separators
        cloaked_key = cloaked_key.replace("\\", "/").replace("//", "/")
        
        print(f"Uploading cloaked file: {local_file_path} -> {cloaked_key}")
        return self.upload_file(local_file_path, cloaked_key)
    
    def initialize_bucket_structure(self):
        """Initialize the S3 bucket with the required folder structure"""
        print(f"Initializing S3 bucket '{self.bucket_name}' with dataset structure...")
        
        # Create the main directory structure
        main_folders = [
            self.uncloaked_prefix,
            self.cloaked_prefix,
            self.locks_prefix,
            self.temp_prefix
        ]
        
        for folder in main_folders:
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=folder,
                    Body=''
                )
                print(f"Created main folder: {folder}")
            except Exception as e:
                print(f"Error creating main folder {folder}: {e}")
        
        # Create the detailed folder structure based on DATASET_REQUIREMENTS
        return self.create_dataset_folder_structure()
    
    def get_processing_statistics(self):
        """Get statistics about processed vs unprocessed files"""
        print("Gathering processing statistics...")
        
        all_uncloaked_files = self.scan_all_subfolders_for_files()
        processed_count = 0
        unprocessed_count = 0
        
        for file_key in all_uncloaked_files:
            if self._is_already_processed(file_key):
                processed_count += 1
            else:
                unprocessed_count += 1
        
        stats = {
            'total_files': len(all_uncloaked_files),
            'processed': processed_count,
            'unprocessed': unprocessed_count,
            'completion_percentage': (processed_count / len(all_uncloaked_files) * 100) if all_uncloaked_files else 0
        }
        
        print(f"Processing Statistics:")
        print(f"  Total files: {stats['total_files']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Unprocessed: {stats['unprocessed']}")
        print(f"  Completion: {stats['completion_percentage']:.2f}%")
        
        return stats
    
    def mark_file_as_failed(self, file_key, error_message="Processing failed"):
        """Mark a file as failed to prevent reprocessing"""
        file_name = os.path.basename(file_key)
        base_name = os.path.splitext(file_name)[0]
        
        failed_key = f"Failed/{base_name}_failed.json"
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=failed_key,
                Body=json.dumps({
                    "original_file": file_key,
                    "error": error_message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "instance_id": self._get_instance_id()
                })
            )
            print(f"Marked file as failed: {file_key}")
            return True
        except Exception as e:
            print(f"Error marking file as failed {file_key}: {e}")
            return False

    def _is_file_failed(self, file_key):
        """Check if a file has been marked as failed"""
        file_name = os.path.basename(file_key)
        base_name = os.path.splitext(file_name)[0]
        
        failed_key = f"Failed/{base_name}_failed.json"
        
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=failed_key)
            return True
        except self.s3_client.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                print(f"Error checking failed status {failed_key}: {e}")
                return False


def setup_aws_environment():
    """Set up AWS credentials and verify access"""
    try:
        # Try to get credentials
        session = boto3.Session()
        credentials = session.get_credentials()
        
        if not credentials:
            print("AWS credentials not found. Please configure AWS CLI or set environment variables.")
            return False
        
        # Test S3 access
        s3_client = boto3.client('s3')
        s3_client.list_buckets()
        
        print("AWS environment setup successful!")
        return True
        
    except Exception as e:
        print(f"Error setting up AWS environment: {e}")
        return False


def get_aws_config_from_args(args):
    """Extract AWS configuration from command line arguments"""
    if not hasattr(args, 'aws_spot') or not args.aws_spot:
        return None
    
    bucket_name = getattr(args, 'aws_bucket', None)
    aws_region = getattr(args, 'aws_region', 'us-east-1')
    
    if not bucket_name:
        print("Error: --aws-bucket is required when using --aws-spot")
        return None
    
    return {
        'bucket_name': bucket_name,
        'aws_region': aws_region
    }


def initialize_aws_dataset_structure(bucket_name, aws_region='eu-west-2'):
    """Initialize AWS S3 bucket with the complete dataset structure"""
    print(f"Setting up AWS S3 dataset structure in bucket: {bucket_name}")
    
    if not setup_aws_environment():
        return False
    
    try:
        s3_handler = AWSS3Handler(bucket_name, aws_region)
        
        # Initialize the bucket structure
        success = s3_handler.initialize_bucket_structure()
        
        if success:
            print("AWS S3 dataset structure initialized successfully!")
            # Get initial statistics
            s3_handler.get_processing_statistics()
        else:
            print("Failed to initialize AWS S3 dataset structure")
        
        return success
        
    except Exception as e:
        print(f"Error initializing AWS dataset structure: {e}")
        return False
