import glob
import os
import json
import shutil
from datetime import datetime

def get_timestamp():
    """Get current timestamp in formatted string"""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

class CloakingLibrary:
    # SINGLETON CLOAKING LIBRARY CLASS
    _instance = None

    # Supported image formats by Fawkes
    SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png']

    # Supported video formats
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.wmv']

    DATASET_REQUIREMENTS = {
        "Images": {
            "Age": {
                "U13": 50,
                "Teen": 75,
                "Adult": 325,
                "Above60": 50
                },
            "Expression": {
                "Smiling": 225,
                "Neutral": 175,
                "Other": 100
            },
            "Gender": {
                "M": 225,
                "F": 225,
                "Other": 25
            },
            "Groups": {
                "Multiple": 150,
                "Single": 350
            },
            "Obstruction": {
                "NoObstruction": 400,
                "WithObstruction": 100
            },
            "Race": {
                "White": 100,
                "South Asian": 145,
                "East Asian": 115,
                "Black": 75,
                "Other": 15
            }
        },

        "Videos": {
            "Age": {
                "U13": 50,
                "Teen": 75,
                "Adult": 325,
                "Above60": 50
                },
            "Expression": {
                "Smiling": 225,
                "Neutral": 175,
                "Other": 100
            },
            "Gender": {
                "M": 225,
                "F": 225,
                "Other": 25
            },
            "Groups": {
                "Multiple": 150,
                "Single": 350
            },
            "Obstruction": {
                "NoObstruction": 400,
                "WithObstruction": 100
            },
            "Race": {
                "White": 100,
                "South Asian": 145,
                "East Asian": 115,
                "Black": 75,
                "Other": 15
            }
        }
    }


    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CloakingLibrary, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, make_dirs = False):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            base_dir = os.path.dirname(os.path.abspath(__file__))

            if not make_dirs:
                return
            
            self.cloaking_lib_dir = os.path.join(base_dir, "CloakingLibrary")
            os.makedirs(self.cloaking_lib_dir, exist_ok=True)
            self.info_json_path = os.path.join(self.cloaking_lib_dir, "dataset_info.json")
            if not os.path.exists(self.info_json_path):
                with open(self.info_json_path, "w") as f:
                    json.dump([], f, indent=4)
            
            self.data_dir = os.path.join(self.cloaking_lib_dir, "Dataset")
            
            os.makedirs(self.data_dir, exist_ok=True)


            #Inner directory paths
            cloaked_dir = os.path.join(self.data_dir, "Cloaked")
            original_dir = os.path.join(self.data_dir, "Uncloaked")

            self.unsorted_dir = os.path.join(self.data_dir, "Unsorted")
            os.makedirs(self.unsorted_dir, exist_ok=True)

            for dir_path in [cloaked_dir, original_dir]:
                os.makedirs(dir_path, exist_ok=True)
                for img_vid_path in self.DATASET_REQUIREMENTS.keys():
                    img_vid_path_dir = os.path.join(dir_path, img_vid_path)
                    os.makedirs(img_vid_path_dir, exist_ok=True)
                    for classification in self.DATASET_REQUIREMENTS[img_vid_path].keys():
                        os.makedirs(os.path.join(img_vid_path_dir, classification), exist_ok=True)
                        for sub_dir in self.DATASET_REQUIREMENTS[img_vid_path][classification]:
                            os.makedirs(os.path.join(img_vid_path_dir, classification, sub_dir), exist_ok=True)

    def get_media_type(self, ext):
        if ext in self.SUPPORTED_IMAGE_FORMATS:
            return "image"
        elif ext in self.SUPPORTED_VIDEO_FORMATS:
            return "video"
        else:
            return "unsupported"
        
    def get_classification(self, main_classification, sub_classification):
        """Returns the classification string in the format 'main:sub'"""
        return f"{main_classification}:{sub_classification}"
    
    def get_main_and_sub_classification(self, classification):
        """Returns the main and sub classification from a classification string"""
        if ':' in classification:
            parts = classification.split(':')
            if len(parts) == 2:
                return parts[0], parts[1]
        return None, None
        
    def count_json_classification(self, media_type, main_classification, sub_classification):
        """Counts the number of files in the dataset with a specific classification"""
        if media_type not in ['image', 'video']:
            return 0
        
        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        count = 0
        classification = self.get_classification(main_classification, sub_classification)
        for entry in file_data:
            if entry.get("media_type") == media_type and classification in entry.get("classifications", []):
                count += 1
        
        return count
        
    def choose_classification(self, media_type, classifications):
        """Based on classifications, choose the least populated classification for the media type"""
        if media_type not in ['image', 'video']:
            return "none"
        
        # Get the requirements for the media type
        requirements = self.DATASET_REQUIREMENTS[media_type.capitalize()+"s"]
        
        # Find the least populated classification
        least_populated = None
        lowest = float('inf')
        
        for classification in classifications:
            main_classification, sub_classification = self.get_main_and_sub_classification(classification)

            required_count = requirements[main_classification][sub_classification]
            count = self.count_json_classification(media_type, main_classification, sub_classification)
            proportion = (count / required_count) if required_count > 0 else 0
            if proportion < lowest:
                lowest = proportion
                least_populated = classification

        return least_populated if least_populated else 'none'

    def get_unsorted_files(self):
        """Returns a list of unsorted files in the dataset"""
        unsorted_files = []
        
        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        for entry in file_data:
            if entry.get("classifications", None) == []:
                unsorted_files.append("Unsorted/" + entry["file_name"])

        return unsorted_files
    
    def get_unnamed_files(self):
        """Returns a list of files in the dataset that have no person name assigned"""
        unnamed_files = []
        
        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        for entry in file_data:
            if entry["person_name"] == "" and entry.get("cloak_level", "none") == "none":
                if entry.get("actual_classification", None) == "none":
                    unnamed_files.append("Unsorted/" + entry["file_name"])
                else:
                    main_classification, sub_classification = self.get_main_and_sub_classification(entry["actual_classification"])
                    unnamed_files.append(main_classification + "/" + sub_classification + "/" + entry["file_name"])

        return unnamed_files

    def classify_original(self, file_path, classifications, name):
        """Finds finds the actual classification from classifications, and moves original and cloaked versions in the info to appropriate folders""" 
        if not os.path.isfile(file_path):
            print(f"{get_timestamp()} Error: File '{file_path}' does not exist!")
            return False
        
        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        # Get file extension
        ext = os.path.splitext(file_path)[1]
        media_type = self.get_media_type(ext)
        if media_type == "unsupported":
            print(f"{get_timestamp()} Unsupported file format: {ext}")
            return False
        
        # Check if classifications are valid
        for classification in classifications:
            main_classification, sub_classification = self.get_main_and_sub_classification(classification)
            if main_classification not in self.DATASET_REQUIREMENTS[media_type.capitalize()+"s"] or sub_classification not in self.DATASET_REQUIREMENTS[media_type.capitalize()+"s"][main_classification]:
                print(f"{get_timestamp()} Invalid classification: {classification}")
                return False
        if not classifications:
            print(f"{get_timestamp()} No classifications provided, cannot classify the file.")
            return False

        # Choose classification
        actual_classification = self.choose_classification(media_type, classifications)

        # Find the original file entry
        original_file_name = os.path.basename(file_path)
        for entry in file_data:
            if entry["file_name"] == original_file_name and entry["media_type"] == media_type:
                entry["classifications"] = classifications
                entry["actual_classification"] = actual_classification
                entry["person_name"] = name  # Update person name

                # Move original file to the appropriate classification folder
                main_classification, sub_classification = self.get_main_and_sub_classification(actual_classification)
                
                new_path = os.path.join(self.data_dir, "Uncloaked", media_type.capitalize()+"s", main_classification, sub_classification, original_file_name)
                # Move the original file
                original_path = os.path.join(self.unsorted_dir, original_file_name)
                if os.path.exists(original_path):
                    shutil.move(original_path, new_path)
                    print(f"{get_timestamp()} Moved original file {original_file_name} to {new_path}")
            
            elif entry.get("original_file_name", None) == original_file_name and entry["cloak_level"] != "none":
                print(f"{get_timestamp()} Found cloaked file entry for {original_file_name}, updating classification and moving file...")

                # Update the entry with the new classifications and actual classification
                entry["name"] = name

                # Move cloaked file to the appropriate classification folder
                cloaked_file_name = entry["file_name"]
                
                # Get the main and sub classifications
                main_classification, sub_classification = self.get_main_and_sub_classification(actual_classification)
                
                # Determine the new path for the cloaked file
                new_cloaked_path = os.path.join(self.data_dir, "Cloaked", media_type.capitalize()+"s", main_classification, sub_classification, cloaked_file_name)
                
                # Move the cloaked file
                original_cloaked_path = os.path.join(self.unsorted_dir, cloaked_file_name)
                if os.path.exists(original_cloaked_path):
                    shutil.move(original_cloaked_path, new_cloaked_path)
                    print(f"{get_timestamp()} Moved cloaked file {cloaked_file_name} to {new_cloaked_path}")

        # Save updated info.json
        with open(self.info_json_path, "w") as f:
            json.dump(file_data, f, indent=4)

        return True
    
    def get_cloaked_files_from_filepath(self, file_path):
        """Checks the same directory as the file_path for cloaked files with the same base name"""
        # ignore if file_path is already a cloaked file
        # If the file itself is a cloaked file (matches *_cloaked_<level>.<ext>), ignore
        base = os.path.basename(file_path)
        if any(base.endswith(f"_cloaked_{level}{os.path.splitext(base)[1]}") for level in ['low', 'mid', 'high']):
            print(f"{get_timestamp()} File {base} is not an original non cloaked file, ignoring...")
            return []


        directory = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        suffixes = ['low', 'mid', 'high']
        cloaked_files = []
        for suffix in suffixes:
            pattern = os.path.join(directory, f"{base_name}_cloaked_{suffix}.*")
            cloaked_files.extend(glob.glob(pattern))
        return cloaked_files

    def add_to_library(self, original_file_path, cloaked_file_path, cloaking_level, person_name, classifications=[]):
        """Adds a compatible image or video to the library"""

        print(f"{get_timestamp()} Adding {os.path.basename(original_file_path)} and {os.path.basename(cloaked_file_path)} to the library with cloaking level {cloaking_level} for person '{person_name}'")

        # TODO: Fix logic about adding different levels of cloaking on the same image - will currently add original image multiple times with different names
        
        # Check if files exist
        if not os.path.isfile(original_file_path):
            print(f"{get_timestamp()} Original file not found: {original_file_path}")
            return False
        if not os.path.isfile(cloaked_file_path):
            print(f"{get_timestamp()} Cloaked file not found: {cloaked_file_path}")
            return False
        
        original_ext = os.path.splitext(os.path.basename(original_file_path))[1]
        if not (original_ext in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS):
            print(f"{get_timestamp()} Original file {os.path.basename(original_file_path)} has non compatible format for dataset. Supported formats:", " ".join(self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS))
            return False
        
        cloaked_ext = os.path.splitext(os.path.basename(cloaked_file_path))[1]
        if not (cloaked_ext in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS):
            print(f"{get_timestamp()} Cloaked file {os.path.basename(cloaked_file_path)} has non compatible format for dataset. Supported formats:", " ".join(self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS))
            return False

        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        # Get base filename and extension
        orig_base = os.path.basename(original_file_path)
        base_name, ext = os.path.splitext(orig_base)

        # Find a non-clashing filename for the original
        candidate_name = base_name
        counter = 0
        existing_names = {entry["file_name"] for entry in file_data}
        while True:
            candidate_file_name = f"{candidate_name}{ext}"
            if candidate_file_name not in existing_names and not os.path.exists(os.path.join(self.data_dir, candidate_file_name)):
                break
            counter += 1
            candidate_name = f"{base_name}_{counter}"

        original_new_file_name = f"{candidate_name}{ext}"

        actual_classification = self.choose_classification(self.get_media_type(original_ext), classifications)
        main_actual_classification, sub_actual_classification = self.get_main_and_sub_classification(actual_classification)
        if actual_classification != "none":
            original_new_path = os.path.join(self.data_dir, "Uncloaked", self.get_media_type(original_ext).capitalize()+"s", main_actual_classification, sub_actual_classification, original_new_file_name)
        else:
            # If no classification, keep it in Unsorted
            original_new_path = os.path.join(self.data_dir, "Unsorted", original_new_file_name)

        # Copy original file
        shutil.copy2(original_file_path, original_new_path)

        # Add original file entry
        file_data.append({
            "file_name": original_new_file_name,
            "person_name": person_name,
            "media_type": self.get_media_type(original_ext),
            "cloak_level": "none",
            "classifications": classifications,  # List of classifications, empty for unsorted
            'actual_classification': actual_classification,
        })

        # Prepare cloaked file name
        cloaked_level_str = str(cloaking_level)
        cloaked_file_name = f"{candidate_name}_cloaked_{cloaked_level_str}{ext}"

        if actual_classification != "none":
            cloaked_new_path = os.path.join(self.data_dir, "Cloaked", self.get_media_type(original_ext).capitalize()+"s", main_actual_classification, sub_actual_classification, cloaked_file_name)
        else:
            # If no classification, keep it in Unsorted
            cloaked_new_path = os.path.join(self.data_dir, "Unsorted", cloaked_file_name)

        # Copy cloaked file
        shutil.copy2(cloaked_file_path, cloaked_new_path)

        # Add cloaked file entry
        file_data.append({
            "file_name": cloaked_file_name,
            "person_name": person_name,
            "media_type": self.get_media_type(original_ext),
            "cloak_level": cloaked_level_str,
            "original_file_name": original_new_file_name,
        })

        # Save updated info.json
        with open(self.info_json_path, "w") as f:
            json.dump(file_data, f, indent=4)

        return True
