import os
import json
import shutil

class CloakingLibrary:
    # SINGLETON CLOAKING LIBRARY CLASS
    _instance = None

    # Supported image formats by Fawkes
    SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png']

    # Supported video formats
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.wmv']

    DATASET_REQUIREMENTS = { #TODO: CHANGED to total sample (Cloaked+Uncloaked - numbers not divisible by 4)
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
                "Brown": 145,
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
                "Brown": 145,
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
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            base_dir = os.path.dirname(os.path.abspath(__file__))

            self.cloaking_lib_dir = os.path.join(base_dir, "CloakingLibrary")
            self.info_json_path = os.path.join(self.cloaking_lib_dir, "dataset_info.json")
            if not os.path.exists(self.info_json_path):
                with open(self.info_json_path, "w") as f:
                    json.dump([], f, indent=4)
            
            self.data_dir = os.path.join(self.cloaking_lib_dir, "Dataset")
            
            os.makedirs(self.data_dir, exist_ok=True)

            inner_dirs = {
                'Age': ['U13', 'Teen', 'Adult', 'Above60'],
                'Gender': ['M', 'F', 'Other'],
                'Groups': ['Multiple', 'Single'],
                'Expression': ['Smiling', 'Neutral', 'Other'],
                'Obstruction': ['NoObstruction', 'WithObstruction']
            }

            #Inner directory paths
            cloaked_dir = os.path.join(self.data_dir, "Cloaked")
            original_dir = os.path.join(self.data_dir, "Uncloaked")

            self.unsorted_dir = os.path.join(self.data_dir, "Unsorted")
            os.makedirs(self.unsorted_dir, exist_ok=True)

            for dir_path in [cloaked_dir, original_dir]:
                os.makedirs(dir_path, exist_ok=True)
                for img_vid_path in ['Images', 'Videos']:
                    img_vid_path_dir = os.path.join(dir_path, img_vid_path)
                    os.makedirs(img_vid_path_dir, exist_ok=True)
                    for classification in ['Age', 'Gender', 'Groups', 'Expression', 'Obstruction']:
                        os.makedirs(os.path.join(img_vid_path_dir, classification), exist_ok=True)
                        for sub_dir in inner_dirs[classification]:
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
            return None
        
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
                least_populated = (classification, sub_classification)

        return self.get_classification(least_populated[0], least_populated[1]) if least_populated else 'none'

    def get_unsorted_files(self):
        """Returns a list of unsorted files in the dataset"""
        unsorted_files = []
        
        # Load info.json
        with open(self.info_json_path, "r") as f:
            file_data = json.load(f)

        for entry in file_data:
            if entry.get("classifications", None) == []:
                unsorted_files.append(entry["file_name"])
        
        return unsorted_files        
    
    def add_to_library(self, original_file_path, cloaked_file_path, cloaking_level, person_name, classifications=[]):
        """Adds a compatible image or video to the library"""

        print(f"Adding {os.path.basename(original_file_path)} and {os.path.basename(cloaked_file_path)} to the library with cloaking level {cloaking_level} for person '{person_name}'")

        # TODO: Fix logic about adding different levels of cloaking on the same image - will currently add original image multiple times with different names
        
        # Check if files exist
        if not os.path.isfile(original_file_path):
            print(f"Original file not found: {original_file_path}")
            return False
        if not os.path.isfile(cloaked_file_path):
            print(f"Cloaked file not found: {cloaked_file_path}")
            return False
        
        original_ext = os.path.splitext(os.path.basename(original_file_path))[1]
        if not (original_ext in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS):
            print(f"Original file {os.path.basename(original_file_path)} has non compatible format for dataset. Supported formats:", " ".join(self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS))
            return False
        
        cloaked_ext = os.path.splitext(os.path.basename(cloaked_file_path))[1]
        if not (cloaked_ext in self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS):
            print(f"Cloaked file {os.path.basename(cloaked_file_path)} has non compatible format for dataset. Supported formats:", " ".join(self.SUPPORTED_IMAGE_FORMATS + self.SUPPORTED_VIDEO_FORMATS))
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
        original_new_path = os.path.join(self.data_dir, "Unsorted", original_new_file_name) #TODO: do sorted too

        # Copy original file
        shutil.copy2(original_file_path, original_new_path)

        # Add original file entry
        file_data.append({
            "file_name": original_new_file_name,
            "person_name": person_name,
            "media_type": self.get_media_type(original_ext),
            "cloak_level": "none",
            "classifications": classifications,  # List of classifications, empty for unsorted
            'actual_classification': self.choose_classification(self.get_media_type(original_ext), classifications),
        })

        # Prepare cloaked file name
        cloaked_level_str = str(cloaking_level)
        cloaked_file_name = f"{candidate_name}_cloaked_{cloaked_level_str}{ext}"
        cloaked_new_path = os.path.join(self.data_dir, "Unsorted", cloaked_file_name) #TODO: do sorted too

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
