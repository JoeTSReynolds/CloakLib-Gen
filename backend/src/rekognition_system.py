# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# PDX-License-Identifier: MIT-0 (For details, see https://github.com/awsdocs/amazon-rekognition-developer-guide/blob/master/LICENSE-SAMPLECODE.)

import boto3
from botocore.exceptions import ClientError
import json
import os
boto3.client('rekognition', region_name='eu-west-2')
from collections import defaultdict
from dotenv import load_dotenv
import argparse

class FaceRecognitionSystem:
    def __init__(self, profile_name='default', region='eu-west-2'):
        """Initialize the face recognition system with AWS credentials"""
        try:
            session = boto3.Session(profile_name=profile_name, region_name=region)
            self.client = session.client('rekognition')
        except Exception as e:
            print(f"Error initializing AWS session: {e}")
            raise

    def create_collection(self, collection_id):
        """Create a new face collection"""
        try:
            response = self.client.create_collection(CollectionId=collection_id)
            print(f"Collection '{collection_id}' created successfully")
            print(f"Collection ARN: {response['CollectionArn']}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceAlreadyExistsException':
                print(f"Collection '{collection_id}' already exists")
                return True
            else:
                print(f"Error creating collection: {e}")
                return False

    def list_collections(self):
        """List all available collections"""
        try:
            response = self.client.list_collections()
            print("Available collections:")
            for collection in response['CollectionIds']:
                print(f"  - {collection}")
            return response['CollectionIds']
        except ClientError as e:
            print(f"Error listing collections: {e}")
            return []

    def add_faces_to_collection(self, bucket, photo, collection_id, person_name=None):
        """Add faces from an image to the collection"""
        try:
            external_id = person_name or photo
            response = self.client.index_faces(
                CollectionId=collection_id,
                Image={'S3Object': {'Bucket': bucket, 'Name': photo}},
                ExternalImageId=external_id,
                MaxFaces=1,
                QualityFilter="AUTO",
                DetectionAttributes=['ALL']
            )

            print(f'Results for {photo} (Person: {external_id})')
            print('Faces indexed:')
            for faceRecord in response['FaceRecords']:
                print(f"  Face ID: {faceRecord['Face']['FaceId']}")
                print(f"  External ID: {faceRecord['Face']['ExternalImageId']}")
                print(f"  Confidence: {faceRecord['Face']['Confidence']:.2f}%")
                print(f"  Location: {faceRecord['Face']['BoundingBox']}")

            print('Faces not indexed:')
            for unindexedFace in response['UnindexedFaces']:
                print(f" Location: {unindexedFace['FaceDetail']['BoundingBox']}")
                print(' Reasons:')
                for reason in unindexedFace['Reasons']:
                    print(f'   {reason}')
            
            return len(response['FaceRecords'])
        except ClientError as e:
            print(f"Error adding faces: {e}")
            return 0

    def search_faces_by_image(self, bucket, photo, collection_id, threshold=80.0):
        """Search for faces in the collection using an input image"""
        try:
            response = self.client.search_faces_by_image(
                CollectionId=collection_id,
                Image={'S3Object': {'Bucket': bucket, 'Name': photo}},
                FaceMatchThreshold=threshold,
                MaxFaces=5
            )

            print(f"\nSearching for faces in {photo}...")
            print(f"Found {len(response['FaceMatches'])} matches:")
            
            #for match in response['FaceMatches']:
            #    face = match['Face']
                #print(f"  Match found:")
                #print(f"    Person: {face['ExternalImageId']}")
                #print(f"    Face ID: {face['FaceId']}")
                #print(f"    Similarity: {match['Similarity']:.2f}%")
                #print(f"    Confidence: {face['Confidence']:.2f}%")
                #print()

            if not response['FaceMatches']:
                print("  No matching faces found in the collection")
            
            return response['FaceMatches']
        except ClientError as e:
            print(f"Error searching faces: {e}")
            return []

    def list_faces_in_collection(self, collection_id):
        """List all faces in a collection, grouped by ExternalImageId"""
        try:
            response = self.client.list_faces(CollectionId=collection_id)
            faces = response['Faces']

            #print(f"\nFaces in collection '{collection_id}':")
            grouped_faces = defaultdict(list)
            for face in faces:
                grouped_faces[face['ExternalImageId']].append(face)

            # for external_id, face_list in grouped_faces.items():
            #     print(f"\nPerson: {external_id} ({len(face_list)} face(s))")
            #     for face in face_list:
            #         print(f"  Face ID: {face['FaceId']}")
            #         print(f"  Confidence: {face['Confidence']:.2f}%")

            return faces

        except ClientError as e:
            print(f"Error listing faces: {e}")
            return []
        
    def build_and_save_faceid_map(self, collection_id, json_filename='faceid_name_map.json'):
        faceid_map = defaultdict(list)
        pagination_token = None

        while True:
            if pagination_token:
                response = self.client.list_faces(
                    CollectionId=collection_id,
                    MaxResults=1000,
                    NextToken=pagination_token
                )
            else:
                response = self.client.list_faces(
                    CollectionId=collection_id,
                    MaxResults=1000
                )

            for face in response['Faces']:
                face_id = face['FaceId']
                name = face.get('ExternalImageId', 'Unknown')
                faceid_map[name].append(face_id)

            pagination_token = response.get('NextToken')
            if not pagination_token:
                break

        # Save to JSON file
        with open(json_filename, 'w') as f:
            json.dump(faceid_map, f, indent=2)

        print(f" FaceId map saved to {json_filename}")

    def upload_to_s3(self, image_bytes, filename, profile_name='default', region='eu-west-2', bucket_name='cloakingbucket'):
        """Upload image bytes to S3 bucket"""
        try:
            session = boto3.Session(profile_name=profile_name, region_name=region)
            s3_client = session.client('s3')
            s3_client.put_object(
                Bucket=bucket_name,
                Key=filename,
                Body=image_bytes,
                ContentType='image/jpeg'
            )
            return True
        except Exception as e:
            print(f"Error uploading to S3: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Test images against amazon rekognition")
    parser.add_argument("--add", action="store_true", help="Add faces to collection")
    args = parser.parse_args()



    # Configuration
    load_dotenv()  # Load environment variables from .env file

    bucket = os.getenv("AWS_BUCKET_NAME", 'cloakingbucket')
    collection_id = os.getenv("COLLECTION_ID", 'my-face-collection')
    profile_name = os.getenv("AWS_PROFILE_NAME", 'sajida_config')

    print(f"Using bucket: {bucket}")
    print(f"Using collection ID: {collection_id}")
    print(f"Using AWS profile: {profile_name}")

    # Initialize the face recognition system
    face_system = FaceRecognitionSystem(profile_name=profile_name)
    
    # Step 1: Create collection
    print("Step 1: Creating/checking collection...")
    face_system.create_collection(collection_id)
    
    # Step 2: List existing collections
    print("\nStep 2: Listing collections...")
    face_system.list_collections()
    
    if args.add:
        # Step 3: Add faces to collection (enrollment phase)
        print("\nAdding faces to collection since add flag was selected...")
        # Create Image IDs (Names) using images uploaded in S3 AWS Console
        enrollment_images = []

        # Define the folders and corresponding names
        people_folders = {
            'Will Smith Cloaked Low': 'Will_Smith',
            #'Jennifer Lawrence': 'Jennifer_Lawrence'
        }

        # Get the current directory (where this script is located)
        base_dir = os.path.dirname(os.path.abspath(__file__))

        for folder, person_name in people_folders.items():
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path):
                print(f"Warning: Folder '{folder_path}' does not exist.")
                continue
            for filename in os.listdir(folder_path):
                file_path = os.path.join(folder_path, filename)
                if os.path.isfile(file_path):
                    if face_system.upload_to_s3(open(file_path, 'rb').read(), filename, profile_name=profile_name, region='eu-west-2', bucket_name=bucket):
                        print(f"Uploaded {filename} to S3 bucket '{bucket}'")
                        enrollment_images.append((filename, person_name))
                    else:
                        print(f"Failed to upload {filename} to S3 bucket '{bucket}'")
        
        total_faces_indexed = 0
        for photo, person_name in enrollment_images:
            print(f"\nEnrolling {person_name}...")
            indexed_count = face_system.add_faces_to_collection(bucket, photo, collection_id, person_name)
            total_faces_indexed += indexed_count
        
        print(f"\nTotal faces indexed: {total_faces_indexed}")
    
    # Step 4: List all faces in collection
    print("\nStep 3: Listing all enrolled faces...")
    face_system.list_faces_in_collection(collection_id)

    # Step 4.1:Load saved map
    with open('faceid_name_map.json', 'r') as f:
        faceid_map = json.load(f)

    # Invert it: FaceId → Name
    faceid_to_name = {
        face_id: name
        for name, face_ids in faceid_map.items()
        for face_id in face_ids
}

    # Step 4.2: Create map 
    print("\nStep 3.2: Creating map...")
    face_system.build_and_save_faceid_map(collection_id)
    
    # Step 5: Search for faces (recognition phase)
    print("\nStep 4: Testing face recognition...")
    test_images = ['will-smith-test.jpg', 'jennifer-lawrence-test.jpg']

    for test_image in test_images:
        print(f"\n--- Testing with {test_image} ---")
        face_system.upload_to_s3(open(test_image, 'rb').read(), test_image, profile_name=profile_name, region='eu-west-2', bucket_name=bucket)
        matches = face_system.search_faces_by_image(bucket, test_image, collection_id)

        if not matches:
            print("❌ No face match found.")
            continue

        identity_matches = defaultdict(list)
        total_confidence = 0
        num_positive_matches = 0
        face_id_matches_list = []
        
        for match in matches:
            face_id = match['Face']['FaceId']
            face_id_matches_list.append(face_id)
            similarity = match['Similarity']
            total_confidence += match['Similarity']
            name = faceid_to_name.get(face_id, 'Unknown')
            num_positive_matches += 1
            #print(f"✅ {name}: best match = {similarity:.2f}%")
        average = total_confidence/num_positive_matches
        print(f"✅ {name}: average match = {round(average, 3)}%")
        print(f"Matched Face ID's: {face_id_matches_list}")

if __name__ == "__main__":
    main()