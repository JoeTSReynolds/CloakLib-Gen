import os
import sys
import argparse
import glob
import shutil
import cv2
import time
from datetime import datetime, timezone
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import AWS spot handling modules
from aws_spot_handler import AWSS3Handler, SpotInterruptHandler, setup_aws_environment, get_aws_config_from_args

from cloaklib import CloakingLibrary

def get_timestamp():
    """Get current timestamp in formatted string"""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

cloaking_library_instance = CloakingLibrary()

# Image formats that can be converted to supported formats
CONVERTIBLE_IMAGE_FORMATS = ['.webp', '.bmp', '.tiff', '.tif', '.gif']


##### HELPERS ######
def is_image_supported(file_path):
    """Check if an image file is supported by Fawkes"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in cloaking_library_instance.SUPPORTED_IMAGE_FORMATS

def is_image_convertible(file_path):
    """Check if an image file can be converted to a supported format"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in CONVERTIBLE_IMAGE_FORMATS

def convert_image_to_supported_format(image_path, output_dir):
    """Convert an unsupported image format to PNG"""
    try:
        # Read the image
        image = cv2.imread(image_path)
        if image is None:
            print(f"{get_timestamp()} Warning: Could not read image {image_path}")
            return None
        
        # Create output filename with PNG extension
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}.png")
        
        # Save as PNG
        cv2.imwrite(output_path, image)
        print(f"{get_timestamp()} Converted {os.path.basename(image_path)} to PNG format")
        return output_path
    except Exception as e:
        print(f"{get_timestamp()} Error converting {image_path}: {str(e)}")
        return None

def is_video_supported(file_path):
    """Check if a video file is supported for processing"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in cloaking_library_instance.SUPPORTED_VIDEO_FORMATS

def process_image_batch(image_paths, fawkes_protector, batch_id=0, classifications=[], name="", same_dir=False):
    """Process a batch of images with Fawkes"""
    try:
        # Create temporary directory for this batch
        temp_dir = os.path.join(os.path.dirname(image_paths[0]), f"temp_batch_{batch_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Copy images to temp directory
        temp_image_paths = []
        for image_path in image_paths:
            filename = os.path.basename(image_path)
            temp_image_path = os.path.join(temp_dir, filename)
            shutil.copy2(image_path, temp_image_path)
            temp_image_paths.append(temp_image_path)
        

        # Process batch with Fawkes
        result = fawkes_protector.run_protection(
            temp_image_paths,
            batch_size=len(temp_image_paths),
            format='png',
            separate_target=True,
            debug=False,
            no_align=False
        )
        
        success_count = 0
        # Copy results to appropriate directories
        if not same_dir:
            for i, image_path in enumerate(image_paths):
                print(f"{get_timestamp()} Adding to library:", image_path)
                if cloaking_library_instance.add_to_library(image_path, image_path, fawkes_protector.mode, name, classifications): #TODO: Is this correct imagepath?
                    success_count += 1
        else:
            success_count += 1

        shutil.rmtree(temp_dir)
        return success_count
        
    except Exception as e:
        print(f"{get_timestamp()} Error processing batch {batch_id}: {str(e)}")
        return 0

def process_image(image_path, fawkes_protector, classifications=[], name="", same_dir=False):
    """Process a single image with Fawkes"""
    return process_image_batch([image_path], fawkes_protector, 0, classifications, name, same_dir)

def extract_frames(video_path, output_dir):
    """Extract frames from a video file"""
    vidcap = cv2.VideoCapture(video_path)
    success, image = vidcap.read()
    
    fps = vidcap.get(cv2.CAP_PROP_FPS)
    frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count/fps
    
    print(f"{get_timestamp()} Video has {frame_count} frames with FPS {fps} (duration: {duration:.2f}s)")
    
    count = 0
    frame_paths = []
    
    with tqdm(total=frame_count, desc="Extracting frames") as pbar:
        while success:
            frame_path = os.path.join(output_dir, f"frame_{count:05d}.png")
            cv2.imwrite(frame_path, image)
            frame_paths.append(frame_path)
            success, image = vidcap.read()
            count += 1
            pbar.update(1)
            
    vidcap.release()
    return frame_paths, fps

def create_video_from_frames(original_path, frame_dir, output_path, fps, fawkes_protector, classifications, name):
    """Create a video from a directory of frames"""
    frame_files = sorted(glob.glob(os.path.join(frame_dir, "frame_*.png")))
    if not frame_files:
        print(f"{get_timestamp()} No frames found to create video")
        return False
        
    # Read the first frame to get dimensions
    frame = cv2.imread(frame_files[0])
    height, width, _ = frame.shape
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    # Add each frame to the video
    with tqdm(total=len(frame_files), desc="Creating video") as pbar:
        for frame_file in frame_files:
            frame = cv2.imread(frame_file)
            video_writer.write(frame)
            pbar.update(1)
    
    video_writer.release()
    return cloaking_library_instance.add_to_library(original_path, output_path, fawkes_protector.mode, name, classifications)

def process_video_frames_batch(frame_paths, fawkes_protector, cloaked_frames_dir, batch_id):
    """Process a batch of video frames"""
    try:
        # Create temporary directory for this batch
        temp_dir = os.path.join(os.path.dirname(frame_paths[0]), f"temp_video_batch_{batch_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Copy frames to temp directory
        temp_frame_paths = []
        for frame_path in frame_paths:
            filename = os.path.basename(frame_path)
            temp_frame_path = os.path.join(temp_dir, filename)
            shutil.copy2(frame_path, temp_frame_path)
            temp_frame_paths.append(temp_frame_path)
        
        # Process batch with Fawkes
        result = fawkes_protector.run_protection(
            temp_frame_paths,
            batch_size=len(temp_frame_paths),
            format='png',
            separate_target=True,
            debug=False,
            no_align=False
        )
        
        # Copy cloaked frames or fallback to original
        for i, frame_path in enumerate(frame_paths):
            frame_filename = os.path.basename(frame_path)
            base_name = os.path.splitext(frame_filename)[0]
            
            cloaked_filename = f"{base_name}_cloaked.png" #TODO: Should this be png?
            cloaked_path = os.path.join(temp_dir, cloaked_filename)
            
            dest_path = os.path.join(cloaked_frames_dir, frame_filename)
            
            if os.path.exists(cloaked_path):
                shutil.copy2(cloaked_path, dest_path)
            else:
                # If cloaking failed, use original frame
                shutil.copy2(frame_path, dest_path)
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        return len(frame_paths)
        
    except Exception as e:
        print(f"{get_timestamp()} Error processing video frame batch {batch_id}: {str(e)}")
        # Copy original frames as fallback
        for frame_path in frame_paths:
            frame_filename = os.path.basename(frame_path)
            dest_path = os.path.join(cloaked_frames_dir, frame_filename)
            shutil.copy2(frame_path, dest_path)
        return 0

def process_video(video_path, fawkes_protector, batch_size=10, num_threads=1, classifications=[], name=""):
    """Process a video by extracting frames, cloaking each frame, and recombining"""
    try:
        filename = os.path.basename(video_path)
        
        # Create temporary directories
        temp_dir = os.path.join(os.path.dirname(video_path), "temp_video")
        frames_dir = os.path.join(temp_dir, "frames")
        cloaked_frames_dir = os.path.join(temp_dir, "cloaked_frames")
        
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(cloaked_frames_dir, exist_ok=True)
        
        print(f"{get_timestamp()} Processing video: {filename}")
        
        # Extract frames from video
        frame_paths, fps = extract_frames(video_path, frames_dir)
        
        # Process frames in batches
        print(f"{get_timestamp()} Cloaking {len(frame_paths)} frames in batches of {batch_size}...")
        
        # Create batches
        frame_batches = [frame_paths[i:i + batch_size] for i in range(0, len(frame_paths), batch_size)]
        
        if num_threads > 1:
            # Process batches with threading
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                for batch_id, batch in enumerate(frame_batches):
                    future = executor.submit(process_video_frames_batch, batch, fawkes_protector, cloaked_frames_dir, batch_id)
                    futures.append(future)
                
                # Wait for all batches to complete with progress bar
                with tqdm(total=len(frame_batches), desc="Processing frame batches") as pbar:
                    for future in as_completed(futures):
                        future.result()
                        pbar.update(1)
        else:
            # Process batches sequentially
            for batch_id, batch in enumerate(tqdm(frame_batches, desc="Processing frame batches")):
                process_video_frames_batch(batch, fawkes_protector, cloaked_frames_dir, batch_id)
        
        # Create output video from cloaked frames
        output_filename = f"temp_{filename}"
        output_path = os.path.join(temp_dir, output_filename)

        success = create_video_from_frames(video_path, cloaked_frames_dir, output_path, fps, fawkes_protector, classifications, name)

        # Clean up temp directory
        shutil.rmtree(temp_dir)
        
        if success:
            print(f"{get_timestamp()} Successfully processed video: {filename}")
            return True
        else:
            print(f"{get_timestamp()} Failed to create cloaked video: {filename}")
            return False
    except Exception as e:
        print(f"{get_timestamp()} Error processing video {filename}: {str(e)}")
        return False

def process_single_image(image_path, fawkes_protector, classifications=[], name="", same_dir=False):
    """Process a single image file"""
    
    # Check if image needs conversion
    converted_path = None
    if is_image_convertible(image_path):
        temp_dir = os.path.join(os.path.dirname(image_path), "temp_conversion")
        os.makedirs(temp_dir, exist_ok=True)
        converted_path = convert_image_to_supported_format(image_path, temp_dir)
        if converted_path:
            image_path = converted_path
        else:
            print(f"{get_timestamp()} Failed to convert {image_path}")
            return False
    elif not is_image_supported(image_path):
        print(f"{get_timestamp()} Unsupported image format: {image_path}")
        return False

    success = process_image(image_path, fawkes_protector, classifications, name, same_dir)

    # Clean up converted file if it was created
    if converted_path and os.path.exists(converted_path):
        temp_dir = os.path.dirname(converted_path)
        shutil.rmtree(temp_dir)
    
    return success > 0


def process_directory(input_dir, batch_size=10, num_threads=1, mode="high", classifications=[], name=""):
    """Process all supported files in the input directory"""
    
    print(f"{get_timestamp()} Initializing Fawkes protector...")
    
    from fawkes.protection import Fawkes

    # Initialize Fawkes protector
    try:
        fawkes_protector = Fawkes(
            feature_extractor="arcface_extractor_0",
            gpu="0",  # Use GPU 0, change as needed
            batch_size=batch_size,
            mode=mode
        )
        print(f"{get_timestamp()} Fawkes protector initialized with mode: {mode}")
    except Exception as e:
        print(f"{get_timestamp()} Failed to initialize Fawkes: {str(e)}")
        sys.exit(1)
    
    # Get all files in the input directory
    all_files = glob.glob(os.path.join(input_dir, "*"))
    
    # Separate supported, convertible, and video files
    image_files = [f for f in all_files if is_image_supported(f)]
    convertible_files = [f for f in all_files if is_image_convertible(f)]
    video_files = [f for f in all_files if is_video_supported(f)]
    
    print(f"{get_timestamp()} Found {len(image_files)} supported images to process")
    print(f"{get_timestamp()} Found {len(convertible_files)} convertible images to process")
    
    # Convert unsupported images first
    converted_images = []
    if convertible_files:
        temp_conversion_dir = os.path.join(input_dir, "temp_conversions")
        os.makedirs(temp_conversion_dir, exist_ok=True)
        
        for convertible_file in convertible_files:
            print(f"Converting {os.path.basename(convertible_file)}...")
            converted_path = convert_image_to_supported_format(convertible_file, temp_conversion_dir)
            if converted_path:
                converted_images.append(converted_path)
    
    # Combine all images to process
    all_image_files = image_files + converted_images
    
    img_success = 0
    if all_image_files:
        if num_threads > 1 and len(all_image_files) > 1:
            # Process images with threading
            image_batches = [all_image_files[i:i + batch_size] for i in range(0, len(all_image_files), batch_size)]
            
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                for batch_id, batch in enumerate(image_batches):
                    future = executor.submit(process_image_batch, batch, fawkes_protector, batch_id)
                    futures.append(future)
                
                with tqdm(total=len(image_batches), desc="Processing image batches") as pbar:
                    for future in as_completed(futures):
                        img_success += future.result()
                        pbar.update(1)
        else:
            # Process images sequentially
            for i, img_file in enumerate(all_image_files):
                print(f"\nProcessing image {i+1}/{len(all_image_files)}: {os.path.basename(img_file)}")
                img_success += process_image(img_file, fawkes_protector)
    else:
        print("No supported images found to process.")
    
    # Clean up conversion directory
    if convertible_files:
        temp_conversion_dir = os.path.join(input_dir, "temp_conversions")
        if os.path.exists(temp_conversion_dir):
            shutil.rmtree(temp_conversion_dir)
    
    # Process videos
    print(f"\nFound {len(video_files)} supported videos to process")
    
    vid_success = 0
    if video_files:
        for i, vid_file in enumerate(video_files):
            print(f"\nProcessing video {i+1}/{len(video_files)}: {os.path.basename(vid_file)}")
            if process_video(vid_file, fawkes_protector, batch_size, num_threads, classifications, name):
                vid_success += 1
    else:
        print("No supported videos found to process.")
    
    # Print summary
    print("\n" + "="*50)
    print("PROCESSING SUMMARY")
    print("="*50)
    print(f"Images: Successfully processed {img_success}/{len(all_image_files)}")
    if convertible_files:
        print(f"Converted images: {len(converted_images)}/{len(convertible_files)}")
    print(f"Videos: Successfully processed {vid_success}/{len(video_files)}")
    print(f"Skipped: {len(all_files) - len(image_files) - len(convertible_files) - len(video_files)} unsupported files")
    print("="*50)

### AWS SPOT INSTANCE FUNCTIONS ###

def process_aws_spot_instance(bucket_name, aws_region='eu-west-2', cloak_level='mid', batch_size=10, all_levels=False):
    """Main function for AWS spot instance processing"""
    
    # Set up AWS environment
    print("Setting up AWS environment...")
    if not setup_aws_environment():
        return False
    
    # Initialize S3 handler
    s3_handler = AWSS3Handler(bucket_name, aws_region)
    # One-time sync of local tracker with current S3 state (list-only)
    s3_handler.sync_local_tracker()
    
    # Set up cleanup callback for graceful shutdown
    def cleanup_callback():
        print("Performing cleanup before shutdown...")
        try:
            # Release any pre-acquired locks we haven't processed yet
            s3_handler.release_all_locks()
        except Exception as e:
            print(f"Error releasing pending locks during cleanup: {e}")
    
    # Initialize spot interrupt handler
    interrupt_handler = SpotInterruptHandler(s3_handler.s3_client, bucket_name, cleanup_callback, s3_handler)
    interrupt_handler.start_monitoring()
    
    # New queue-based main processing loop (queue of up to 3 locked items)
    processed_count = 0
    queue = []  # each element: {file_key, lock_key, media_type}
    while not interrupt_handler.interrupted:
        # Refill queue if empty (acquire locks up-front)
        if not queue:
            queue = s3_handler.build_processing_queue(desired_count=3, target_level=cloak_level, all_levels=all_levels)
            if not queue:
                print("No files in queue. Sleeping 45s before retry...")
                time.sleep(45)
                continue
            else:
                print(f"Queue filled with {len(queue)} item(s).")

        current = queue.pop(0)
        file_key = current['file_key']
        lock_key = current['lock_key']
        interrupt_handler.set_current_lock(lock_key)

        # Determine missing levels once per file (minimize HEAD operations)
        file_ext = os.path.splitext(file_key)[1].lower()
        is_video = file_ext in s3_handler.SUPPORTED_VIDEO_FORMATS
        if is_video:
            # Policy: only process mid for videos regardless of flags
            target_video_level = 'mid'
            missing_levels = [] if s3_handler.already_has_level(file_key, target_video_level) else [target_video_level]
        else:
            if all_levels:
                missing_levels = s3_handler.determine_missing_levels(file_key)
            else:
                missing_levels = [] if s3_handler.already_has_level(file_key, cloak_level) else [cloak_level]

        if not missing_levels:
            print(f"Skipping {file_key}; no missing levels (locally tracked).")
            s3_handler.release_lock(lock_key)
            interrupt_handler.set_current_lock(None)
            continue

        print(f"\nProcessing {file_key} (levels: {missing_levels})")

        # Download original just-in-time to save disk space
        work_dir = "/tmp/cloaking_queue_work"
        os.makedirs(work_dir, exist_ok=True)
        local_name = os.path.basename(file_key)
        local_path = os.path.join(work_dir, local_name)
        if not s3_handler.download_file(file_key, local_path):
            print(f"Failed to download {file_key}, releasing lock.")
            s3_handler.release_lock(lock_key)
            interrupt_handler.set_current_lock(None)
            continue

        ext = os.path.splitext(local_name)[1].lower()
        media_type = 'image' if ext in s3_handler.SUPPORTED_IMAGE_FORMATS else 'video'

        try:
            for level in missing_levels:
                if interrupt_handler.interrupted:
                    break
                # Adjust Fawkes mode for this level (re-init if needed)
                 # Initialize Fawkes protector
                from fawkes.protection import Fawkes
                try:
                    fawkes_protector = Fawkes(
                        feature_extractor="arcface_extractor_0",
                        gpu="0",
                        batch_size=batch_size,
                        mode=level
                    )
                except Exception as e:
                    print(f"Failed to initialize Fawkes: {str(e)}")
                    return False
                print(f"  - Level {level} starting for {file_key}")
                if media_type == 'image':
                    ok = process_aws_image(local_path, file_key, s3_handler, fawkes_protector, level)
                else:
                    ok = process_aws_video(local_path, file_key, s3_handler, fawkes_protector, level, batch_size, interrupt_handler)
                if ok:
                    s3_handler.mark_level_processed_local(file_key, level, media_type)
                    print(f"  - Level {level} completed")
                else:
                    print(f"  - Level {level} failed; stopping further levels for this file")
                    # Mark file as failed in S3 so other instances skip it
                    s3_handler.mark_file_as_failed(file_key, f"Processing failed at level {level}")
                    break
            if s3_handler.is_fully_processed_local(file_key):
                processed_count += 1
                print(f"File fully processed: {file_key} (Total fully processed: {processed_count})")
        except Exception as e:
            print(f"Error processing {file_key}: {e}")
        finally:
            # Release lock only after all intended levels
            if lock_key:
                s3_handler.release_lock(lock_key)
                interrupt_handler.set_current_lock(None)
            # Cleanup local file to conserve disk
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
                # Remove work dir if empty
                if os.path.isdir(work_dir) and not os.listdir(work_dir):
                    os.rmdir(work_dir)
            except Exception:
                pass
            # No mid-batch refill: queue will be refilled only when empty to honor 3-lock batch semantics.
    
    print(f"Spot instance processing completed. Total files processed: {processed_count}")
    return True


def process_aws_file(file_key, s3_handler, fawkes_protector, cloak_level, batch_size, interrupt_handler):
    """Process a single file from AWS S3"""
    
    # Create local working directory
    work_dir = "/tmp/cloaking_work"
    os.makedirs(work_dir, exist_ok=True)
    
    # Download the file
    file_name = os.path.basename(file_key)
    local_file_path = os.path.join(work_dir, file_name)
    
    if not s3_handler.download_file(file_key, local_file_path):
        return False
    
    # Determine file type
    ext = os.path.splitext(file_name)[1].lower()
    
    try:
        if ext in s3_handler.SUPPORTED_IMAGE_FORMATS:
            # Process image
            success = process_aws_image(local_file_path, file_key, s3_handler, fawkes_protector, cloak_level)
        
        elif ext in s3_handler.SUPPORTED_VIDEO_FORMATS:
            # Process video (with interruption handling)
            success = process_aws_video(local_file_path, file_key, s3_handler, fawkes_protector, cloak_level, batch_size, interrupt_handler)
        
        else:
            print(f"Unsupported file format: {ext}")
            success = False
    
    finally:
        # Clean up local files
        if os.path.exists(local_file_path):
            os.remove(local_file_path)

        if os.path.exists(work_dir):
            # Clean up working directory
            shutil.rmtree(work_dir)

    # If failed to process, mark as failed in S3
    if not success:
        s3_handler.mark_file_as_failed(file_key, f"Failed to process file, marking as failed in S3: {file_name}")
        return False

    return success


def process_aws_image(local_file_path, original_s3_key, s3_handler, fawkes_protector, cloak_level):
    """Process a single image for AWS spot instance"""
    temp_dir = None
    try:
        # Create temporary directory for processing
        temp_dir = os.path.join(os.path.dirname(local_file_path), "temp_image")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Copy image to temp directory
        filename = os.path.basename(local_file_path)
        temp_image_path = os.path.join(temp_dir, filename)
        shutil.copy2(local_file_path, temp_image_path)
        
        # Process with Fawkes
        result = fawkes_protector.run_protection(
            [temp_image_path],
            batch_size=1,
            format='png',
            separate_target=True,
            debug=False,
            no_align=False
        )
        
        # Find the cloaked output
        base_name = os.path.splitext(filename)[0]
        ext = os.path.splitext(filename)[1]
        cloaked_filename = f"{base_name}_cloaked.png" #TODO: Should this be png?
        cloaked_path = os.path.join(temp_dir, cloaked_filename)
        
        if os.path.exists(cloaked_path):
            # Upload cloaked file to S3
            success = s3_handler.upload_processed_file(cloaked_path, original_s3_key, cloak_level)
        else:
            print(f"Cloaked file not found: {cloaked_path}")
            success = False
        
        return success
        
    except Exception as e:
        print(f"Error processing image {local_file_path}: {e}")
        return False
    
    finally:
        # Ensure temp directory is cleaned up
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def process_aws_video(local_file_path, original_s3_key, s3_handler, fawkes_protector, cloak_level, batch_size, interrupt_handler):
    """Process a video for AWS spot instance with interruption handling"""
    frames_dir = None
    cloaked_frames_dir = None
    output_path = None
    frame_work_dir = None

    try:
        filename = os.path.basename(local_file_path)
        base_name = os.path.splitext(filename)[0]
        
        # Create working directories
        work_dir = os.path.dirname(local_file_path)
        frames_dir = os.path.join(work_dir, f"{base_name}_frames")
        cloaked_frames_dir = os.path.join(work_dir, f"{base_name}_cloaked_frames")
        frame_work_dir = os.path.join(work_dir, f"{base_name}_frame_work")
        
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(cloaked_frames_dir, exist_ok=True)
        os.makedirs(frame_work_dir, exist_ok=True)
        
        # Check for existing progress
        progress_data = s3_handler.load_temp_video_progress(original_s3_key)
        
        if progress_data:
            print(f"Resuming video processing from frame {progress_data.get('last_processed_frame', 0)}")
            
            # Download existing temp frames
            downloaded_frames = s3_handler.download_temp_frames(original_s3_key, cloaked_frames_dir)
            fps = progress_data['fps']
            total_frames = progress_data['total_frames']
            last_processed = progress_data.get('last_processed_frame', 0)
            
            # Extract remaining frames
            remaining_frames = extract_video_frames_from_position(local_file_path, frames_dir, last_processed)
            # After extracting remaining frames, delete the original local video to save disk
            try:
                if os.path.exists(local_file_path):
                    os.remove(local_file_path)
            except Exception:
                pass
            
        else:
            # Start fresh - extract all frames
            print(f"Starting fresh video processing: {filename}")
            frame_paths, fps = extract_frames(local_file_path, frames_dir)
            total_frames = len(frame_paths)
            last_processed = 0
            
            # Save initial progress
            progress_data = {
                'fps': fps,
                'total_frames': total_frames,
                'last_processed_frame': 0,
                'cloak_level': cloak_level,
                'started_at': datetime.now(timezone.utc).isoformat()
            }
            s3_handler.save_temp_video_progress(original_s3_key, progress_data)
            # Delete the original local video to conserve disk
            try:
                if os.path.exists(local_file_path):
                    os.remove(local_file_path)
            except Exception:
                pass
        
        # Process frames one-by-one to minimize memory; upload to S3 after each
        remaining_frame_pattern = os.path.join(frames_dir, "frame_*.png")
        all_frames = sorted(glob.glob(remaining_frame_pattern))
        remaining_frames = [f for f in all_frames if int(os.path.basename(f).split('_')[1].split('.')[0]) >= last_processed]

        if not remaining_frames:
            remaining_frames = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))

        total_remaining = len(remaining_frames)
        with tqdm(total=total_remaining, desc="Processing frames") as pbar:
            for idx, frame_path in enumerate(remaining_frames, start=0):
                if interrupt_handler.interrupted:
                    print("Interruption detected during video processing. Saving progress...")
                    break

                frame_filename = os.path.basename(frame_path)
                frame_index = int(frame_filename.split('_')[1].split('.')[0])

                # Prepare isolated work dir to avoid Fawkes scanning the whole frames dir
                try:
                    # Clean frame_work_dir
                    for f in os.listdir(frame_work_dir):
                        try:
                            os.remove(os.path.join(frame_work_dir, f))
                        except Exception:
                            pass
                except Exception:
                    pass

                temp_frame_path = os.path.join(frame_work_dir, frame_filename)
                try:
                    shutil.copy2(frame_path, temp_frame_path)
                except Exception as e:
                    print(f"Failed to stage frame {frame_filename}: {e}")
                    # Mark as failed frame: copy original to cloaked to keep sequence
                    dest_path = os.path.join(cloaked_frames_dir, frame_filename)
                    try:
                        shutil.copy2(frame_path, dest_path)
                    except Exception:
                        pass
                    # Upload placeholder to S3 for continuity
                    temp_key = f"{s3_handler.temp_prefix}{base_name}_frames/{frame_filename}"
                    s3_handler.upload_file(dest_path if os.path.exists(dest_path) else frame_path, temp_key)
                    # Update progress and move on
                    progress_data['last_processed_frame'] = frame_index + 1
                    s3_handler.save_temp_video_progress(original_s3_key, progress_data)
                    try:
                        os.remove(frame_path)
                    except Exception:
                        pass
                    pbar.update(1)
                    continue

                # Run Fawkes on this single frame
                try:
                    fawkes_protector.run_protection(
                        [temp_frame_path],
                        batch_size=1,
                        format='png',
                        separate_target=True,
                        debug=False,
                        no_align=False
                    )
                except Exception as e:
                    print(f"Fawkes failed on frame {frame_filename}: {e}")

                # Determine cloaked output and place into cloaked_frames_dir using original name
                base_no_ext = os.path.splitext(frame_filename)[0]
                cloaked_candidate = os.path.join(frame_work_dir, f"{base_no_ext}_cloaked.png")
                dest_path = os.path.join(cloaked_frames_dir, frame_filename)

                try:
                    if os.path.exists(cloaked_candidate):
                        shutil.copy2(cloaked_candidate, dest_path)
                    else:
                        # fallback to original if cloaking failed
                        shutil.copy2(frame_path, dest_path)
                except Exception as e:
                    print(f"Error copying cloaked frame {frame_filename}: {e}")

                # Upload this cloaked frame immediately to S3 temp folder
                temp_key = f"{s3_handler.temp_prefix}{base_name}_frames/{frame_filename}"
                s3_handler.upload_file(dest_path, temp_key)

                # Update progress after this frame
                progress_data['last_processed_frame'] = frame_index + 1
                s3_handler.save_temp_video_progress(original_s3_key, progress_data)

                # Remove the local original frame to save disk
                try:
                    os.remove(frame_path)
                except Exception:
                    pass

                # Also clear frame_work_dir artifacts for this frame
                try:
                    for f in os.listdir(frame_work_dir):
                        try:
                            os.remove(os.path.join(frame_work_dir, f))
                        except Exception:
                            pass
                except Exception:
                    pass

                pbar.update(1)
        
        # If processing completed without interruption
        if not interrupt_handler.interrupted:
            # Ensure all temp frames are uploaded (no-op if already uploaded per-frame)
            s3_handler.upload_temp_frames(cloaked_frames_dir, original_s3_key)
            
            # Create final video
            output_filename = f"{base_name}_cloaked_{cloak_level}.mp4"
            output_path = os.path.join(work_dir, output_filename)
            
            success = create_video_from_frames_aws(cloaked_frames_dir, output_path, fps)
            
            if success:
                # Upload final video to S3
                success = s3_handler.upload_processed_file(output_path, original_s3_key, cloak_level)

                if success:

                    # Clean up temp files in S3
                    s3_handler.cleanup_temp_files(original_s3_key)
            
            # Clean up local directories
            shutil.rmtree(frames_dir, ignore_errors=True)
            shutil.rmtree(cloaked_frames_dir, ignore_errors=True)

            if output_path and os.path.exists(output_path):
                os.remove(output_path)  # Clean up local video file

            return success
        
        else:
            # Interrupted - upload current progress
            print("Uploading partial progress before shutdown...")
            s3_handler.upload_temp_frames(cloaked_frames_dir, original_s3_key)
            
            # Clean up local directories
            shutil.rmtree(frames_dir, ignore_errors=True)
            shutil.rmtree(cloaked_frames_dir, ignore_errors=True)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)  # Clean up local video file
            
            return False  # Will be resumed later
    
    except Exception as e:
        print(f"Error processing video {local_file_path}: {e}")
        return False
    
    finally:
        # Always clean up local directories and files
        if frames_dir and os.path.exists(frames_dir):
            shutil.rmtree(frames_dir, ignore_errors=True)
        if cloaked_frames_dir and os.path.exists(cloaked_frames_dir):
            shutil.rmtree(cloaked_frames_dir, ignore_errors=True)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        if frame_work_dir and os.path.exists(frame_work_dir):
            shutil.rmtree(frame_work_dir, ignore_errors=True)


def extract_video_frames_from_position(video_path, output_dir, start_frame):
    """Extract video frames starting from a specific frame number"""
    vidcap = cv2.VideoCapture(video_path)
    
    # Set the starting position
    vidcap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    
    success, image = vidcap.read()
    count = start_frame
    frame_paths = []
    
    while success:
        frame_path = os.path.join(output_dir, f"frame_{count:05d}.png")
        cv2.imwrite(frame_path, image)
        frame_paths.append(frame_path)
        success, image = vidcap.read()
        count += 1
    
    vidcap.release()
    return frame_paths


def create_video_from_frames_aws(frames_dir, output_path, fps):
    """Create a video from frames directory for AWS processing"""
    frame_files = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    if not frame_files:
        print("No frames found to create video")
        return False
    
    # Read the first frame to get dimensions
    frame = cv2.imread(frame_files[0])
    if frame is None:
        print("Could not read first frame")
        return False
    
    height, width, _ = frame.shape
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    # Add each frame to the video
    for frame_file in tqdm(frame_files, desc="Creating video"):
        frame = cv2.imread(frame_file)
        if frame is not None:
            video_writer.write(frame)
    
    video_writer.release()
    return True


### PUBLIC FUNCTIONS ###
# These functions can be called from other scripts or modules

def perform_cloaking(input, classifications=[], name="", cloaking_mode='mid', threads=1, batch_size=10):
    """Main function to cloak a folder of images/videos or a single file (image/video)"""

    dir_to_check = os.path.abspath(os.path.join(os.path.dirname(__file__), input))

    # If input is a directory, process all files in the directory
    if os.path.isdir(dir_to_check):
        process_directory(
            input_dir=dir_to_check,
            batch_size=batch_size,
            num_threads=threads,
            mode=cloaking_mode,
            classifications=classifications,
            name=name
        )
        print("Cloaking completed.")
        return
    

    # If input is a file, determine if it's an image or video
    input_file = os.path.abspath(input)
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"'{input_file}' does not exist.")

    
    from fawkes.protection import Fawkes

    # Video file
    if is_video_supported(input_file):
        try:
            fawkes_protector = Fawkes(
                feature_extractor="arcface_extractor_0",
                gpu="0",
                batch_size=batch_size,
                mode=cloaking_mode
            )
        except Exception as e:
            print(f"Failed to initialize Fawkes: {str(e)}")
            return

        success = process_video(input_file, fawkes_protector, batch_size, threads, classifications, name)
        print("\n" + "="*50)
        print("PROCESSING SUMMARY")
        print("="*50)
        print(f"Video: {'Successfully processed' if success else 'Failed to process'}")
        print("="*50)
        print("Cloaking completed.")
        return

    # Image file (supported or convertible)
    elif is_image_supported(input_file) or is_image_convertible(input_file):
        print("Initializing Fawkes protector for image processing...")
        try:
            fawkes_protector = Fawkes(
                feature_extractor="arcface_extractor_0",
                gpu="0",
                batch_size=batch_size,
                mode=cloaking_mode
            )
            print(f"Fawkes protector initialized with mode: {cloaking_mode}")
        except Exception as e:
            print(f"Failed to initialize Fawkes: {str(e)}")
            return

        success = process_single_image(input_file, fawkes_protector, classifications, name)
        print("\n" + "="*50)
        print("PROCESSING SUMMARY")
        print("="*50)
        print(f"Image: {'Successfully processed' if success else 'Failed to process'}")
        print("="*50)
        print("Cloaking completed.")
        return

    else:
        print(f"Error: Unsupported file format: {input_file}")
        print(f"Supported image formats: {', '.join(cloaking_library_instance.SUPPORTED_IMAGE_FORMATS)}")
        print(f"Convertible image formats: {', '.join(CONVERTIBLE_IMAGE_FORMATS)}")
        print(f"Supported video formats: {', '.join(cloaking_library_instance.SUPPORTED_VIDEO_FORMATS)}")
        return




def main():
    parser = argparse.ArgumentParser(description="Process images and videos with Fawkes cloaking, and add them to a dataset library. Two modes: Cloak and Classify.")

    # Mutually exclusive group for modes
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--cloak", action="store_true", help="Enable cloak mode. This will cloak the file/folder and add it to the library. If no name or no classifications are provided, it will be added to the Unsorted folder in the library.")
    mode_group.add_argument("--classify", action="store_true", help="Enable classify mode. This is used to reclassify files that have already been cloaked. It will not cloak the file again, but will add the classifications to the library. Provide the file path and name/classifications as arguments. Use --list to list files in the unsorted folder requiring classifications.")
    mode_group.add_argument("--aws-spot", action="store_true", help="Enable AWS spot instance mode for automatic S3 processing")

    # Arguments common to both modes (but not AWS spot mode)
    # Custom logic to make input_path required except for --classify --list/--sync/--check or --aws-spot
    if (
        ("--classify" in sys.argv and ("--list" in sys.argv or "--sync" in sys.argv or "--check" in sys.argv)) or
        "--aws-spot" in sys.argv
    ):
        # Don't require input_path for these subcommands
        parser.add_argument("input_path", type=str, nargs="?", help="Image file to process, or directory if --dir is specified (not needed for --aws-spot)")
    else:
        parser.add_argument("input_path", type=str, help="Image file to process, or directory if --dir is specified")
    parser.add_argument("--dir", action="store_true", help="Process all files in the specified directory")
    parser.add_argument("--name", type=str, default="", help="Name of the person (e.g., Beyonce)")
    parser.add_argument("--age", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Age"].keys(), help="Age category")
    parser.add_argument("--expression", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Expression"].keys(), help="Facial expression")
    parser.add_argument("--gender", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Gender"].keys(), help="Gender")
    parser.add_argument("--group", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Groups"].keys(), help="Specify if image has a single person or multiple people")
    parser.add_argument("--obstruction", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Obstruction"].keys(), help="Specify if there is NoObstruction or WithObstruction")
    parser.add_argument("--race", type=str, default=None, choices=cloaking_library_instance.DATASET_REQUIREMENTS["Images"]["Race"].keys(), help="Specify the race category")

    # Cloak mode only arguments
    parser.add_argument("--mode", type=str, default="mid", choices=["low", "mid", "high"], 
                       help="Fawkes protection mode, specify the level of cloaking. Default is 'mid'.")    
    parser.add_argument("--batch-size", type=int, default=10, help="Number of images to process in each batch")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads to use for processing")

    # AWS Spot Instance arguments
    parser.add_argument("--aws-bucket", type=str, help="S3 bucket name for AWS spot instance mode (required with --aws-spot)")
    parser.add_argument("--aws-region", type=str, default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--all-levels", action="store_true", help="Process all cloaking levels (low, mid, high) in AWS spot instance mode. Default is to process only the specified level.")

    # Classify mode only arguments
    parser.add_argument("--list", action="store_true", help="List files in the unsorted folder requiring classifications.")
    parser.add_argument("--sync", action="store_true", help="Sync the library with the unsorted folder. Will also run the check command to ensure all files are correctly classified.")
    parser.add_argument("--check", action="store_true", help="Check the library for any issues, such as missing files or incorrect classifications.")

    # Validate argument combinations after parsing
    args = parser.parse_args()

    # Arguments exclusive to cloak mode
    cloak_only_args = ["mode", "batch_size", "threads"]
    # Arguments exclusive to classify mode
    classify_only_args = ["list", "sync", "check"]
    # Arguments exclusive to aws-spot mode
    aws_spot_only_args = ["aws_bucket", "aws_region", "all_levels"]

    # Check for invalid argument combinations
    if args.cloak:
        for arg in classify_only_args:
            if getattr(args, arg):
                parser.error(f"--{arg.replace('_', '-')} can only be used with --classify mode.")
    elif args.classify:
        for arg in cloak_only_args:
            # batch_size and threads default to 10/1, so only error if user explicitly set them
            if arg in ["mode", "batch_size", "threads"]:
                if f"--{arg.replace('_', '-')}" in sys.argv:
                    parser.error(f"--{arg.replace('_', '-')} can only be used with --cloak mode.")
            elif getattr(args, arg) is not None:
                parser.error(f"--{arg.replace('_', '-')} can only be used with --cloak mode.")
    elif args.aws_spot:
        # AWS spot mode can use some cloak arguments (mode, batch_size)
        for arg in classify_only_args:
            if getattr(args, arg):
                parser.error(f"--{arg.replace('_', '-')} can only be used with --classify mode.")

    args = parser.parse_args()

    # AWS Spot Instance Mode
    if args.aws_spot:
        if not args.aws_bucket:
            print("Error: --aws-bucket is required when using --aws-spot mode.")
            sys.exit(1)
        
        print("Starting AWS Spot Instance processing mode...")
        success = process_aws_spot_instance(
            bucket_name=args.aws_bucket,
            aws_region=args.aws_region,
            cloak_level=args.mode,
            batch_size=args.batch_size,
            all_levels=args.all_levels
        )
        
        if success:
            print("AWS Spot Instance processing completed successfully.")
        else:
            print("AWS Spot Instance processing failed.")
            sys.exit(1)
        return

    #Check if cloak mode or classify mode is enabled
    if not args.cloak and not args.classify:
        print("Error: You must specify either cloak, classify, or aws-spot mode.")
        sys.exit(1)
    elif (args.cloak and args.classify):
        print("Error: You cannot specify multiple modes at the same time.")
        sys.exit(1)
    
    classifications = []
    if args.age:
        classifications.append(f"Age:{args.age}")
    if args.expression:
        classifications.append(f"Expression:{args.expression}")
    if args.gender:
        classifications.append(f"Gender:{args.gender}")
    if args.group:
        classifications.append(f"Groups:{args.group}")
    if args.obstruction:
        classifications.append(f"Obstruction:{args.obstruction}")
    if args.race:
        classifications.append(f"Race:{args.race}")

    if (args.classify and not args.list and not classifications) and not args.name:
        print("Error: You must provide at least one classification when using classify mode.")
        sys.exit(1)

    if args.list:
        # List unsorted files requiring classifications
        unsorted_files = cloaking_library_instance.get_unsorted_files()
        unnamed_files = cloaking_library_instance.get_unnamed_files()

        if not unsorted_files and not unnamed_files:
            print("No unsorted files found that require classifications.")
        else:
            print("Unsorted files requiring classifications/naming:")
            for file in unsorted_files:
                if file not in unnamed_files:
                    print(f"- {file} - Reason: No classifications provided")
                else:
                    print(f"- {file} - Reason: No classifications and no name provided")
                    unnamed_files.remove(file)  # Remove from unnamed list to avoid duplicates
            for file in unnamed_files:
                print(f"- {file} - Reason: No name provided")
            
        sys.exit(0)

    if args.sync:
        # Sync the library with the unsorted folder
        print("Syncing library...")
        cloaking_library_instance.sync_unsorted_folder()
        print("Sync completed.")
        print("Running check to ensure all files are correctly classified...")
        cloaking_library_instance.check_library()
        print("Check completed.")
        sys.exit(0)

    if args.check:
        # Check the library for any issues
        print("Checking library for issues...")
        cloaking_library_instance.check_library()
        print("Check completed.")
        sys.exit(0)

    # Get absolute paths
    input_path = os.path.abspath(args.input_path)
    
    # Check if input path exists
    if not os.path.exists(input_path):
        print(f"Error: Input path '{input_path}' does not exist!")
        sys.exit(1)

    if args.classify:
        if args.dir:
            # Process directory for classification
            if not os.path.isdir(input_path):
                print(f"Error: '{input_path}' is not a directory!")
                sys.exit(1)
            
            print(f"Processing directory for classification: {input_path}")
            
            # Get all files in the directory
            for file in os.listdir(input_path):
                file_path = os.path.join(input_path, file)
                if not os.path.isfile(file_path):
                    print(f"Skipping non-file item: {file_path}")
                    continue
                
                # Check if the file is cloaked
                cloaked_files = cloaking_library_instance.get_cloaked_files_from_filepath(file_path)
                if not cloaked_files:
                    print(f"No cloaked versions found for {file}. Cannot classify.")
                    continue
                
                print(f"\nFound cloaked versions of {file}:")
                for cloaked_file in cloaked_files:
                    print(f"- {cloaked_file}")
                
                print()

                # Classify each file
                for file in cloaked_files:
                    cloaking_library_instance.classify_original(file, classifications)
                    print(f"Classifications added successfully for {file}")
            
        else:
            # Process single file for classification
            if not os.path.isfile(input_path):
                print(f"Error: '{input_path}' is not a file!")
                sys.exit(1)
            
            print(f"Processing single file for classification: {input_path}")
            
            # Check if the file is already cloaked
            cloaked_files = cloaking_library_instance.get_cloaked_files_from_filepath(input_path) # TODO: allow for checking other directories, e.g. check library
            if cloaked_files:
                print("Found cloaked versions of the file:")
                for cloaked_file in cloaked_files:
                    print(f"- {cloaked_file}")
                print("Sorting files based on classifications...")
                cloaking_library_instance.classify_original(input_path, classifications)
                print("Classifications added successfully.")
            else:
                print("File is not cloaked. Cannot classify.")
                sys.exit(1)

    elif args.cloak:
        # Cloak mode processing
        if args.dir:
            # Process directory for cloaking
            if not os.path.isdir(input_path):
                print(f"Error: '{input_path}' is not a directory!")
                sys.exit(1)
            
            print(f"Processing directory for cloaking: {input_path}")
            perform_cloaking(input=input_path, classifications=classifications, cloaking_mode=args.mode, threads=args.threads, batch_size=args.batch_size, name=args.name)
        else:
            # Process single file for cloaking
            if not os.path.isfile(input_path):
                print(f"Error: '{input_path}' is not a file!")
                sys.exit(1)
            
            print(f"Processing single file for cloaking: {input_path}")
            perform_cloaking(input=input_path, classifications=classifications, cloaking_mode=args.mode, threads=args.threads, batch_size=args.batch_size, name=args.name)

    

if __name__ == "__main__":
    main()