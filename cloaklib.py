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
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CloakingLibrary, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            base_dir = os.path.dirname(os.path.abspath(__file__))

            self.cloaking_lib_dir = os.path.join(base_dir, "CloakingLibrary")
            self.info_json_path = os.path.join(self.cloaking_lib_dir, "info.json")
            if not os.path.exists(self.info_json_path):
                with open(self.info_json_path, "w") as f:
                    json.dump([], f, indent=4)
            
            self.data_dir = os.path.join(self.cloaking_lib_dir, "Data")
            
            os.makedirs(self.data_dir, exist_ok=True)

    def get_media_type(self, ext):
        if ext in self.SUPPORTED_IMAGE_FORMATS:
            return "image"
        elif ext in self.SUPPORTED_VIDEO_FORMATS:
            return "video"
        else:
            return "unsupported"
    
    def add_to_library(self, original_file_path, cloaked_file_path, cloaking_level, person_id):
        """Adds a compatible image or video to the library"""
        success = False

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
            info = json.load(f)

        if "file_data" not in info:
            info["file_data"] = []

        file_data = info["file_data"]

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
        original_new_path = os.path.join(self.data_dir, original_new_file_name)

        # Copy original file
        shutil.copy2(original_file_path, original_new_path)

        # Add original file entry
        file_data.append({
            "file_name": original_new_file_name,
            "person_id": person_id,
            "media_type": self.get_media_type(original_ext),
            "cloak_level": "none"
        })

        # Prepare cloaked file name
        cloaked_level_str = str(cloaking_level)
        cloaked_file_name = f"{candidate_name}_cloaked_{cloaked_level_str}{ext}"
        cloaked_new_path = os.path.join(self.data_dir, cloaked_file_name)

        # Copy cloaked file
        shutil.copy2(cloaked_file_path, cloaked_new_path)

        # Add cloaked file entry
        file_data.append({
            "file_name": cloaked_file_name,
            "person_id": person_id,
            "media_type": self.get_media_type(original_ext),
            "cloak_level": cloaked_level_str,
            "original_file_name": original_new_file_name
        })

        # Save updated info.json
        with open(self.info_json_path, "w") as f:
            json.dump(info, f, indent=4)

        return True
            

