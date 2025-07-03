#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import glob
import shutil
import cv2
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import Fawkes directly
from fawkes.protection import Fawkes

# Supported image formats by Fawkes
SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png']

# Supported video formats
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.wmv']

def is_image_supported(file_path):
    """Check if an image file is supported by Fawkes"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in SUPPORTED_IMAGE_FORMATS

def is_video_supported(file_path):
    """Check if a video file is supported for processing"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in SUPPORTED_VIDEO_FORMATS

def setup_directories(base_dir):
    """Ensure all required directories exist"""
    img_raw_dir = os.path.join(base_dir, "CloakingLibrary", "Images", "Raw")
    img_cloaked_dir = os.path.join(base_dir, "CloakingLibrary", "Images", "Cloaked")
    vid_raw_dir = os.path.join(base_dir, "CloakingLibrary", "Videos", "Raw")
    vid_cloaked_dir = os.path.join(base_dir, "CloakingLibrary", "Videos", "Cloaked")
    
    os.makedirs(img_raw_dir, exist_ok=True)
    os.makedirs(img_cloaked_dir, exist_ok=True)
    os.makedirs(vid_raw_dir, exist_ok=True)
    os.makedirs(vid_cloaked_dir, exist_ok=True)
    
    return {
        "img_raw": img_raw_dir,
        "img_cloaked": img_cloaked_dir,
        "vid_raw": vid_raw_dir,
        "vid_cloaked": vid_cloaked_dir
    }

def process_image_batch(image_paths, dirs, fawkes_protector, batch_id=0):
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
        for i, image_path in enumerate(image_paths):
            filename = os.path.basename(image_path)
            
            # Copy original to Raw directory
            raw_dest = os.path.join(dirs["img_raw"], filename)
            shutil.copy2(image_path, raw_dest)
            
            # Check for cloaked image
            base_name = os.path.splitext(filename)[0]
            ext = os.path.splitext(filename)[1]
            cloaked_filename = f"{base_name}_cloaked.png"
            cloaked_path = os.path.join(temp_dir, cloaked_filename)
            
            if os.path.exists(cloaked_path):
                # Convert back to original format if needed
                final_cloaked_name = f"{base_name}_cloaked{ext}"
                final_dest = os.path.join(dirs["img_cloaked"], final_cloaked_name)
                shutil.copy2(cloaked_path, final_dest)
                success_count += 1
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        return success_count
        
    except Exception as e:
        print(f"Error processing batch {batch_id}: {str(e)}")
        return 0

def process_image(image_path, dirs, fawkes_protector):
    """Process a single image with Fawkes"""
    return process_image_batch([image_path], dirs, fawkes_protector, 0)

def extract_frames(video_path, output_dir):
    """Extract frames from a video file"""
    vidcap = cv2.VideoCapture(video_path)
    success, image = vidcap.read()
    
    fps = vidcap.get(cv2.CAP_PROP_FPS)
    frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count/fps
    
    print(f"Video has {frame_count} frames with FPS {fps} (duration: {duration:.2f}s)")
    
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

def create_video_from_frames(frame_dir, output_path, fps):
    """Create a video from a directory of frames"""
    frame_files = sorted(glob.glob(os.path.join(frame_dir, "frame_*.png")))
    if not frame_files:
        print("No frames found to create video")
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
    return True

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
            
            cloaked_filename = f"{base_name}_cloaked.png"
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
        print(f"Error processing video frame batch {batch_id}: {str(e)}")
        # Copy original frames as fallback
        for frame_path in frame_paths:
            frame_filename = os.path.basename(frame_path)
            dest_path = os.path.join(cloaked_frames_dir, frame_filename)
            shutil.copy2(frame_path, dest_path)
        return 0

def process_video(video_path, dirs, fawkes_protector, batch_size=10, num_threads=1):
    """Process a video by extracting frames, cloaking each frame, and recombining"""
    try:
        # Copy original to Raw directory
        filename = os.path.basename(video_path)
        raw_dest = os.path.join(dirs["vid_raw"], filename)
        shutil.copy2(video_path, raw_dest)
        
        # Create temporary directories
        temp_dir = os.path.join(os.path.dirname(video_path), "temp_video")
        frames_dir = os.path.join(temp_dir, "frames")
        cloaked_frames_dir = os.path.join(temp_dir, "cloaked_frames")
        
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(cloaked_frames_dir, exist_ok=True)
        
        print(f"Processing video: {filename}")
        
        # Extract frames from video
        frame_paths, fps = extract_frames(video_path, frames_dir)
        
        # Process frames in batches
        print(f"Cloaking {len(frame_paths)} frames in batches of {batch_size}...")
        
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
        output_filename = f"{os.path.splitext(filename)[0]}_cloaked{os.path.splitext(filename)[1]}"
        output_path = os.path.join(dirs["vid_cloaked"], output_filename)
        
        success = create_video_from_frames(cloaked_frames_dir, output_path, fps)
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        
        if success:
            print(f"Successfully processed video: {filename}")
            return True
        else:
            print(f"Failed to create cloaked video: {filename}")
            return False
    except Exception as e:
        print(f"Error processing video {filename}: {str(e)}")
        return False

def process_directory(input_dir, base_dir, batch_size=10, num_threads=1, mode="high"):
    """Process all supported files in the input directory"""
    # Setup directories
    dirs = setup_directories(base_dir)
    
    print("Initializing Fawkes protector...")
    
    # Initialize Fawkes protector
    try:
        fawkes_protector = Fawkes(
            feature_extractor="arcface_extractor_0",
            gpu="0",  # Use GPU 0, change as needed
            batch_size=batch_size,
            mode=mode
        )
        print(f"Fawkes protector initialized with mode: {mode}")
    except Exception as e:
        print(f"Failed to initialize Fawkes: {str(e)}")
        sys.exit(1)
    
    # Get all files in the input directory
    all_files = glob.glob(os.path.join(input_dir, "*"))
    
    # Process images
    image_files = [f for f in all_files if is_image_supported(f)]
    print(f"\nFound {len(image_files)} supported images to process")
    
    img_success = 0
    if image_files:
        if num_threads > 1 and len(image_files) > 1:
            # Process images with threading
            image_batches = [image_files[i:i + batch_size] for i in range(0, len(image_files), batch_size)]
            
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                for batch_id, batch in enumerate(image_batches):
                    future = executor.submit(process_image_batch, batch, dirs, fawkes_protector, batch_id)
                    futures.append(future)
                
                with tqdm(total=len(image_batches), desc="Processing image batches") as pbar:
                    for future in as_completed(futures):
                        img_success += future.result()
                        pbar.update(1)
        else:
            # Process images sequentially
            for i, img_file in enumerate(image_files):
                print(f"\nProcessing image {i+1}/{len(image_files)}: {os.path.basename(img_file)}")
                img_success += process_image(img_file, dirs, fawkes_protector)
    else:
        print("No supported images found to process.")
    
    # Process videos
    video_files = [f for f in all_files if is_video_supported(f)]
    print(f"\nFound {len(video_files)} supported videos to process")
    
    vid_success = 0
    if video_files:
        for i, vid_file in enumerate(video_files):
            print(f"\nProcessing video {i+1}/{len(video_files)}: {os.path.basename(vid_file)}")
            if process_video(vid_file, dirs, fawkes_protector, batch_size, num_threads):
                vid_success += 1
    else:
        print("No supported videos found to process.")
    
    # Print summary
    print("\n" + "="*50)
    print("PROCESSING SUMMARY")
    print("="*50)
    print(f"Images: Successfully processed {img_success}/{len(image_files)}")
    print(f"Videos: Successfully processed {vid_success}/{len(video_files)}")
    print(f"Skipped: {len(all_files) - len(image_files) - len(video_files)} unsupported files")
    print("="*50)

def main():
    parser = argparse.ArgumentParser(description="Process images and videos with Fawkes cloaking")
    parser.add_argument("input_dir", type=str, help="Directory containing images/videos to process")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of images to process in each batch")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads to use for processing")
    parser.add_argument("--mode", type=str, default="mid", choices=["low", "mid", "high"], 
                       help="Fawkes protection mode")
    args = parser.parse_args()
    
    # Get absolute paths
    input_dir = os.path.abspath(args.input_dir)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Check if input directory exists
    if not os.path.exists(input_dir):
        print(f"Error: Input directory '{input_dir}' does not exist!")
        sys.exit(1)
    
    print(f"Processing files from: {input_dir}")
    print(f"Base directory: {base_dir}")
    print(f"Library will be created/updated in: {os.path.join(base_dir, 'CloakingLibrary')}")
    print(f"Batch size: {args.batch_size}")
    print(f"Threads: {args.threads}")
    print(f"Protection mode: {args.mode}")
    
    # Process the directory
    process_directory(input_dir, base_dir, args.batch_size, args.threads, args.mode)

if __name__ == "__main__":
    main()