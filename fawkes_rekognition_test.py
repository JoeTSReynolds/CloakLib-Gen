# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# PDX-License-Identifier: MIT-0 (For details, see https://github.com/awsdocs/amazon-rekognition-developer-guide/blob/master/LICENSE-SAMPLECODE.)

import boto3
from botocore.exceptions import ClientError
import json

class FaceRecognitionSystem:
    def __init__(self, profile_name='default', region='us-east-1'):
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
            
            for match in response['FaceMatches']:
                face = match['Face']
                print(f"  Match found:")
                print(f"    Person: {face['ExternalImageId']}")
                print(f"    Face ID: {face['FaceId']}")
                print(f"    Similarity: {match['Similarity']:.2f}%")
                print(f"    Confidence: {face['Confidence']:.2f}%")
                print()

            if not response['FaceMatches']:
                print("  No matching faces found in the collection")
            
            return response['FaceMatches']
        except ClientError as e:
            print(f"Error searching faces: {e}")
            return []

    def list_faces_in_collection(self, collection_id):
        """List all faces in a collection"""
        try:
            response = self.client.list_faces(CollectionId=collection_id)
            print(f"\nFaces in collection '{collection_id}':")
            for face in response['Faces']:
                print(f"  Face ID: {face['FaceId']}")
                print(f"  External ID: {face['ExternalImageId']}")
                print(f"  Confidence: {face['Confidence']:.2f}%")
                print()
            return response['Faces']
        except ClientError as e:
            print(f"Error listing faces: {e}")
            return []

def main():
    # Configuration
    bucket = 'your-s3-bucket-name'  # Replace with your S3 bucket
    collection_id = 'my-face-collection'
    profile_name = 'default'  # Replace with your AWS profile name
    
    # Initialize the face recognition system
    face_system = FaceRecognitionSystem(profile_name=profile_name)
    
    # Step 1: Create collection
    print("Step 1: Creating/checking collection...")
    face_system.create_collection(collection_id)
    
    # Step 2: List existing collections
    print("\nStep 2: Listing collections...")
    face_system.list_collections()
    
    # Step 3: Add faces to collection (enrollment phase)
    print("\nStep 3: Adding faces to collection...")
    # Replace these with your actual image names in S3
    enrollment_images = [
        ('person1_photo1.jpg', 'John_Doe'),
        ('person2_photo1.jpg', 'Jane_Smith'),
        ('person3_photo1.jpg', 'Bob_Johnson')
    ]
    
    total_faces_indexed = 0
    for photo, person_name in enrollment_images:
        print(f"\nEnrolling {person_name}...")
        indexed_count = face_system.add_faces_to_collection(bucket, photo, collection_id, person_name)
        total_faces_indexed += indexed_count
    
    print(f"\nTotal faces indexed: {total_faces_indexed}")
    
    # Step 4: List all faces in collection
    print("\nStep 4: Listing all enrolled faces...")
    face_system.list_faces_in_collection(collection_id)
    
    # Step 5: Search for faces (recognition phase)
    print("\nStep 5: Testing face recognition...")
    # Replace with your test image names
    test_images = ['test_person1.jpg', 'test_unknown.jpg']
    
    for test_image in test_images:
        print(f"\n--- Testing with {test_image} ---")
        matches = face_system.search_faces_by_image(bucket, test_image, collection_id)

if __name__ == "__main__":
    main()