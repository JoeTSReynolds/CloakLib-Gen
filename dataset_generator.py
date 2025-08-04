import os
import sys
import argparse
import glob
import shutil
import cv2
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from cloaklib import CloakingLibrary
from fawkes.protection import Fawkes

#aws imports 
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import json
boto3.client('rekognition', region_name='eu-west-2')
from collections import defaultdict

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

def process_image_batch(image_paths, fawkes_protector, batch_id=0):
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
            if cloaking_library_instance.add_to_library(image_path, image_path, fawkes_protector.mode, "Tom_Hanks"): #CHANGE TO NAME WANTED & TODO:CHANGE TO THIS
                success_count += 1

        shutil.rmtree(temp_dir)
        return success_count
        
    except Exception as e:
        print(f"Error processing batch {batch_id}: {str(e)}")
        return 0

def process_image(image_path, fawkes_protector):
    """Process a single image with Fawkes"""
    return process_image_batch([image_path], fawkes_protector, 0)

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

def create_video_from_frames(original_path, frame_dir, output_path, fps):
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
    return cloaking_library_instance.add_to_library(original_path, output_path, "high", 1) # TODO: change this

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
        output_filename = f"temp_{filename}"
        output_path = os.path.join(temp_dir, output_filename)
        
        success = create_video_from_frames(video_path, cloaked_frames_dir, output_path, fps)
        
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

def process_single_image(image_path, fawkes_protector):
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
    
    success = process_image(image_path, fawkes_protector)
    
    # Clean up converted file if it was created
    if converted_path and os.path.exists(converted_path):
        temp_dir = os.path.dirname(converted_path)
        shutil.rmtree(temp_dir)
    
    return success > 0


def process_directory(input_dir, batch_size=10, num_threads=1, mode="high"):
    """Process all supported files in the input directory"""
    
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
            if process_video(vid_file, fawkes_protector, batch_size, num_threads):
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

def cloak_folder(input_dir, age=None, expression=None, gender=None, single_person=None, obstructed=None, cloaking_mode='mid', parent_directory=False):
    """Main function to cloak a folder of images/videos"""
    # Determine the directory to check based on parent_directory flag
    if parent_directory:
        dir_to_check = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", input_dir))
    else:
        dir_to_check = os.path.abspath(os.path.join(os.path.dirname(__file__), input_dir))

    if not os.path.isdir(dir_to_check):
        print("Could not find directory")
        raise FileNotFoundError(f"Directory '{dir_to_check}' does not exist.")
    

    print(f"Processing directory: {dir_to_check}")
    print(f"Age: {age}, Expression: {expression}, Gender: {gender}, Single Person: {single_person}, Obstructed: {obstructed}")


    process_directory(
        input_dir=dir_to_check,
        batch_size=10,  # Default batch size
        num_threads=1,  # Default to single thread for simplicity
        mode=cloaking_mode
    )

    print("Cloaking completed.")
    unsorted_files = cloaking_library_instance.get_unsorted_files()

    if len(unsorted_files) > 0:
        print("Unsorted files:")

        for file in unsorted_files:
            print(f"- {file}")

        print("For each of these files, decide on a classification, and run the following command to classify them:")
        print("python dataset_generator.py classify <file_path> <classifications>")
        print("Where <classifications> is one of the following:")
        print("Age: U13, Teen, Adult, Above60")
        print("Expression: Smiling, Neutral, Other")
        print("Gender: M, F, Other")
        print("Groups: Single, Multiple")
        print("Obstruction: WithObstruction, NoObstruction")
        print("Race: White, Brown, Black, EastAsian, Other")
        print("Example: python dataset_generator.py classify /path/to/file.png Age:Adult Expression:Smiling")


def classify_file(file_path, classifications):
    cloaking_library_instance.classify_original(file_path, classifications)

#aws class : work in progress

'''class FaceRecognitionSystem:
    def start_aws(self, profile_name='default', region='eu-west-2'):
        """Initialize the face recognition system with AWS credentials"""
        try:
            session = boto3.Session(profile_name=profile_name, region_name=region)
            self.s3 = session.client("s3")
        except Exception as e:
            print(f"Error initializing AWS session: {e}")
            raise
    def upload_to_s3(self, bucket_name, file_path):
        self.s3.upload_file(file_path, bucket_name)
        print(f"Uploaded {file_path} to s3://{bucket_name}")'''

'''def uploadimagetoaws(file_path, name):
    bucket = 'cloakingbucket'
    profile_name = 'sajida_config'
    collection_id = 'my-face-collection'
    bucket_folder = "uploads/"
    face_system = FaceRecognitionSystem(profile_name=profile_name)
    s3 = boto3.client('s3')

    # Final S3 key (filename in bucket)
    filename = os.path.basename(file_path)
    s3_key = f"{bucket_folder}{name}_{filename}"

    face_system.upload_to_s3(bucket, file_path, s3_key)'''

'''def upload_to_aws(file_path, bucket, object_name):
    #upload file to bucket
    try:
        s3.upload_file(file_path, bucket, object_name)
    print(f"✅ Uploaded: {file_path} → s3://{bucket}/{object_name}")
    except FileNotFoundError:
    print(f"❌ File not found: {file_path}")
    except NoCredentialsError:
    print("❌ AWS credentials not found.")
    except ClientError as e:
        print(f"❌ AWS error: {e}")'''



def main():
    parser = argparse.ArgumentParser(description="Process images and videos with Fawkes cloaking and for uploads")
    parser.add_argument("input_path", type=str, help="Image file to process, or directory if --dir is specified")
    parser.add_argument("--dir", action="store_true", help="Process all files in the specified directory")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of images to process in each batch")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads to use for processing")
    parser.add_argument("--mode", type=str, default="mid", choices=["low", "mid", "high"], 
                       help="Fawkes protection mode")
    parser.add_argument("--name", type=str, default=None, help="Name of the person (e.g., Beyonce)")
    parser.add_argument("--age", type=str, choices=["U13", "Teen", "Adult", "Above60"], help="Age category")
    parser.add_argument("--expression", type=str, choices=["Smiling", "Neutral", "Other"], help="Facial expression")
    parser.add_argument("--gender", type=str, choices=["M", "F", "Other"], help="Gender")
    parser.add_argument("--single", type=str, choices=["Single", "Multiple"], help="Specify if image has a single person")
    parser.add_argument("--obstruction", type=str, choices=["NoObstruction", "WithObstruction"], help="Specify if there is NoObstruction or WithObstruction")
    args = parser.parse_args()
    
    # Get absolute paths
    input_path = os.path.abspath(args.input_path)
    
    # Check if input path exists
    if not os.path.exists(input_path):
        print(f"Error: Input path '{input_path}' does not exist!")
        sys.exit(1)
        
    print(f"Batch size: {args.batch_size}")
    print(f"Threads: {args.threads}")
    print(f"Protection mode: {args.mode}")
    
    if args.dir:
        # Process directory
        if not os.path.isdir(input_path):
            print(f"Error: '{input_path}' is not a directory!")
            sys.exit(1)
        
        print(f"Processing files from directory: {input_path}")
        process_directory(input_path, args.batch_size, args.threads, args.mode)
    else:
        # Process single file
        if os.path.isdir(input_path):
            print(f"Error: '{input_path}' is a directory! Use --dir flag to process directories.")
            sys.exit(1)
        
        print(f"Processing single file: {input_path}")
        
        # Check if it's a video or image
        if is_video_supported(input_path):
            print("Initializing Fawkes protector for video processing...")
            try:
                fawkes_protector = Fawkes(
                    feature_extractor="arcface_extractor_0",
                    gpu="0",
                    batch_size=args.batch_size,
                    mode=args.mode
                )
                print(f"Fawkes protector initialized with mode: {args.mode}")
            except Exception as e:
                print(f"Failed to initialize Fawkes: {str(e)}")
                sys.exit(1)

            success = process_video(input_path, fawkes_protector, args.batch_size, args.threads)
            
            print("\n" + "="*50)
            print("PROCESSING SUMMARY")
            print("="*50)
            print(f"Video: {'Successfully processed' if success else 'Failed to process'}")
            print("="*50)
            
        elif is_image_supported(input_path) or is_image_convertible(input_path):
            print("Initializing Fawkes protector for image processing...")
            try:
                fawkes_protector = Fawkes(
                    feature_extractor="arcface_extractor_0",
                    gpu="0",
                    batch_size=args.batch_size,
                    mode=args.mode
                )
                print(f"Fawkes protector initialized with mode: {args.mode}")
            except Exception as e:
                print(f"Failed to initialize Fawkes: {str(e)}")
                sys.exit(1)
            
            success = process_single_image(input_path, fawkes_protector)
            
            print("\n" + "="*50)
            print("PROCESSING SUMMARY")
            print("="*50)
            print(f"Image: {'Successfully processed' if success else 'Failed to process'}")
            print("="*50)
        else:
            print(f"Error: Unsupported file format: {input_path}")
            print(f"Supported image formats: {', '.join(cloaking_library_instance.SUPPORTED_IMAGE_FORMATS)}")
            print(f"Convertible image formats: {', '.join(CONVERTIBLE_IMAGE_FORMATS)}")
            print(f"Supported video formats: {', '.join(cloaking_library_instance.SUPPORTED_VIDEO_FORMATS)}")
            sys.exit(1)


if __name__ == "__main__":
    main()