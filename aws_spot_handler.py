import boto3
import json
import os
import time
import signal
import sys
import threading
import glob
import shutil
from urllib.request import urlopen
from urllib.error import URLError
import urllib
from datetime import datetime, timezone
from tqdm import tqdm
import cv2
from cloaklib import CloakingLibrary

def get_timestamp():
    """Get current timestamp in formatted string"""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

class SpotInterruptHandler:
    """Handles AWS spot instance interruption gracefully"""
    
    def __init__(self, s3_client, bucket_name, cleanup_callback=None):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.cleanup_callback = cleanup_callback
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
        if self.cleanup_callback:
            self.cleanup_callback()
        self._release_current_lock()
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
                print(f"Released lock: {self.current_lock_key}")
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
            return True
        except Exception as e:
            print(f"Error releasing lock {lock_key}: {e}")
            return False
    
    def _get_instance_id(self):
        """Get the current EC2 instance ID"""
        try:
            response = urlopen("http://169.254.169.254/latest/meta-data/instance-id", timeout=2)
            return response.read().decode('utf-8')
        except:
            return "unknown"
    
    def get_next_file_to_process(self):
        """Find the next uncloaked file that needs processing from all subfolders"""
        # Use the deep scanning method to get all files
        uncloaked_files = self.scan_all_subfolders_for_files()
        
        for file_key in uncloaked_files:
            file_name = os.path.basename(file_key)

            # Check if already processed (look for cloaked versions)
            if self._is_already_processed(file_key):
                continue

            if self._is_file_failed(file_key):
                print(f"Skipping failed file: {file_key}")
                continue

            # Try to create a lock for this file
            lock_key = self.create_lock(file_name)
            if lock_key:
                return file_key, lock_key
        
        return None, None
    
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
        """Find the next uncloaked file that needs processing in any missing protection level"""
        # Use the deep scanning method to get all files
        uncloaked_files = self.scan_all_subfolders_for_files()
        
        for file_key in uncloaked_files:
            file_name = os.path.basename(file_key)

            # Check which levels are missing
            missing_levels = self._get_missing_cloak_levels(file_key)
            
            if not missing_levels:
                continue  # All levels already processed

            if self._is_file_failed(file_key):
                print(f"Skipping failed file: {file_key}")
                continue

            # Try to create a lock for this file
            lock_key = self.create_lock(file_name)
            if lock_key:
                return file_key, lock_key, missing_levels
        
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
