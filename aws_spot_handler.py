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
from datetime import datetime, timezone
from tqdm import tqdm
import cv2

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
        print(f"\nReceived interrupt signal {signum}. Starting graceful shutdown...")
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
        print("Started spot instance interruption monitoring...")
    
    def _monitor_spot_interruption(self):
        """Monitor AWS metadata for spot interruption notice"""
        metadata_url = "http://169.254.169.254/latest/meta-data/spot/instance-action"
        
        while not self.stop_monitoring.is_set():
            try:
                response = urlopen(metadata_url, timeout=2)
                if response.getcode() == 200:
                    print("\n*** SPOT INSTANCE INTERRUPTION DETECTED ***")
                    print("Initiating graceful shutdown...")
                    self._handle_interrupt(signal.SIGTERM, None)
                    break
            except URLError:
                # No interruption notice - this is expected most of the time
                pass
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
    
    def __init__(self, bucket_name, aws_region='us-east-1'):
        self.bucket_name = bucket_name
        self.aws_region = aws_region
        self.s3_client = boto3.client('s3', region_name=aws_region)
        
        # Directory structure in S3
        self.uncloaked_prefix = "dataset/uncloaked/"
        self.cloaked_prefix = "dataset/cloaked/"
        self.locks_prefix = "locks/"
        self.temp_prefix = "temp/"
        
        # Supported formats
        self.SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png']
        self.SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.wmv']
    
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
        except self.s3_client.exceptions.NoSuchKey:
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
        """Find the next uncloaked file that needs processing"""
        uncloaked_files = self.list_files_in_prefix(self.uncloaked_prefix)
        
        for file_key in uncloaked_files:
            # Skip directories
            if file_key.endswith('/'):
                continue
            
            file_name = os.path.basename(file_key)
            
            # Check if file extension is supported
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS:
                continue
            
            # Check if already processed (look for cloaked versions)
            if self._is_already_processed(file_key):
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
        
        # Remove any existing numbering convention if present
        # e.g., "Bella_Ramsey_1.jpg" -> "Bella_Ramsey_1"
        
        # Check for cloaked versions with different levels
        for level in ['low', 'mid', 'high']:
            cloaked_name = f"{base_name}_cloaked_{level}{ext}"
            
            # Construct the expected S3 path for cloaked file
            # Mirror the directory structure from uncloaked to cloaked
            relative_path = uncloaked_file_key[len(self.uncloaked_prefix):]
            cloaked_key = f"{self.cloaked_prefix}{os.path.dirname(relative_path)}/{cloaked_name}".replace("//", "/")
            
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=cloaked_key)
                return True  # Found at least one cloaked version
            except self.s3_client.exceptions.NoSuchKey:
                continue
            except Exception as e:
                print(f"Error checking for cloaked file {cloaked_key}: {e}")
                continue
        
        return False
    
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
        except self.s3_client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            print(f"Error loading temp progress: {e}")
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
        
        # Create cloaked filename
        cloaked_name = f"{base_name}_cloaked_{cloak_level}{ext}"
        
        # Construct cloaked S3 path (mirror directory structure)
        relative_path = original_s3_key[len(self.uncloaked_prefix):]
        cloaked_key = f"{self.cloaked_prefix}{os.path.dirname(relative_path)}/{cloaked_name}".replace("//", "/")
        
        return self.upload_file(local_file_path, cloaked_key)


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
