import os
import sys
import argparse
import glob
import shutil
import cv2
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from cloaklib import CloakingLibrary

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
            print(f"Warning: Could not read image {image_path}")
            return None
        
        # Create output filename with PNG extension
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}.png")
        
        # Save as PNG
        cv2.imwrite(output_path, image)
        print(f"Converted {os.path.basename(image_path)} to PNG format")
        return output_path
    except Exception as e:
        print(f"Error converting {image_path}: {str(e)}")
        return None

def is_video_supported(file_path):
    """Check if a video file is supported for processing"""
    file_ext = os.path.splitext(file_path)[1].lower()
    return file_ext in cloaking_library_instance.SUPPORTED_VIDEO_FORMATS

def process_image_batch(image_paths, fawkes_protector, batch_id=0, classifications=[], name=""):
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
            print("Adding to library:", image_path)
            if cloaking_library_instance.add_to_library(image_path, image_path, fawkes_protector.mode, name, classifications):
                success_count += 1

        shutil.rmtree(temp_dir)
        return success_count
        
    except Exception as e:
        print(f"Error processing batch {batch_id}: {str(e)}")
        return 0

def process_image(image_path, fawkes_protector, classifications=[], name=""):
    """Process a single image with Fawkes"""
    return process_image_batch([image_path], fawkes_protector, 0, classifications, name)

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

def create_video_from_frames(original_path, frame_dir, output_path, fps, fawkes_protector, classifications, name):
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
        output_filename = f"temp_{filename}"
        output_path = os.path.join(temp_dir, output_filename)

        success = create_video_from_frames(video_path, cloaked_frames_dir, output_path, fps, fawkes_protector, classifications, name)

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

def process_single_image(image_path, fawkes_protector, classifications=[], name=""):
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
            print(f"Failed to convert {image_path}")
            return False
    elif not is_image_supported(image_path):
        print(f"Unsupported image format: {image_path}")
        return False

    success = process_image(image_path, fawkes_protector, classifications, name)

    # Clean up converted file if it was created
    if converted_path and os.path.exists(converted_path):
        temp_dir = os.path.dirname(converted_path)
        shutil.rmtree(temp_dir)
    
    return success > 0


def process_directory(input_dir, batch_size=10, num_threads=1, mode="high", classifications=[], name=""):
    """Process all supported files in the input directory"""
    
    print("Initializing Fawkes protector...")
    
    
    from fawkes.protection import Fawkes

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
    
    # Separate supported, convertible, and video files
    image_files = [f for f in all_files if is_image_supported(f)]
    convertible_files = [f for f in all_files if is_image_convertible(f)]
    video_files = [f for f in all_files if is_video_supported(f)]
    
    print(f"\nFound {len(image_files)} supported images to process")
    print(f"Found {len(convertible_files)} convertible images to process")
    
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

    # Arguments common to both modes
    # Custom logic to make input_path required except for --classify --list/--sync/--check
    if (
        ("--classify" in sys.argv and ("--list" in sys.argv or "--sync" in sys.argv or "--check" in sys.argv))
    ):
        # Don't require input_path for these classify subcommands
        parser.add_argument("input_path", type=str, nargs="?", help="Image file to process, or directory if --dir is specified")
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

    # Check for invalid argument combinations
    if args.cloak:
        for arg in classify_only_args:
            if getattr(args, arg):
                parser.error(f"--{arg.replace('_', '-')} can only be used with --classify mode.")
    if args.classify:
        for arg in cloak_only_args:
            # batch_size and threads default to 10/1, so only error if user explicitly set them
            if arg in ["mode", "batch_size", "threads"]:
                if f"--{arg.replace('_', '-')}" in sys.argv:
                    parser.error(f"--{arg.replace('_', '-')} can only be used with --cloak mode.")
            elif getattr(args, arg) is not None:
                parser.error(f"--{arg.replace('_', '-')} can only be used with --cloak mode.")

    args = parser.parse_args()

    #Check if cloak mode or classify mode is enabled
    if not args.cloak and not args.classify:
        print("Error: You must specify either cloak or classify mode.")
        sys.exit(1)
    elif args.cloak and args.classify:
        print("Error: You cannot specify both cloak and classify modes at the same time.")
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