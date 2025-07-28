#!/usr/bin/env python3
"""
Backend service for AWS Rekognition integration
This script provides a bridge between the React Native app and AWS Rekognition
"""

import os
import sys
import json
import boto3
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from botocore.exceptions import ClientError
from collections import defaultdict
import tempfile
import base64
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the parent directory to Python path to import the FaceRecognitionSystem
sys.path.append(str(Path(__file__).parent.parent))

from fawkes_rekognition_test import FaceRecognitionSystem

app = Flask(__name__)
CORS(app)

# Configuration from environment variables
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', 'cloakingbucketdoubleday')
PROFILE_NAME = os.getenv('AWS_PROFILE_NAME', 'joe')
REGION = os.getenv('AWS_REGION', 'eu-west-2')
COLLECTION_ID = os.getenv('COLLECTION_ID', 'my-face-collection')

# Initialize face recognition system
face_system = None
try:
    face_system = FaceRecognitionSystem(PROFILE_NAME, REGION)
    print(f"Initialized AWS Rekognition with profile: {PROFILE_NAME}, region: {REGION}")
except Exception as e:
    print(f"Error initializing AWS Rekognition: {e}")

def upload_to_s3(image_bytes, filename):
    """Upload image bytes to S3 bucket"""
    try:
        session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
        s3_client = session.client('s3')
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=filename,
            Body=image_bytes,
            ContentType='image/jpeg'
        )
        return True
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False

def cleanup_s3_file(filename):
    """Clean up temporary files from S3"""
    try:
        session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
        s3_client = session.client('s3')
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=filename)
        print(f"Cleaned up temporary file: {filename}")
    except Exception as e:
        print(f"Error cleaning up S3 file {filename}: {e}")

@app.route('/api/enroll-face', methods=['POST'])
def enroll_face():
    print("Received request to enroll face")
    s3_filename = None
    try:
        data = request.json
        image_data = data.get('imageData')  # Base64 encoded image
        person_name = data.get('personName').replace(' ', '_')  # Normalize name for S3 filename
        
        if not image_data or not person_name:
            return jsonify({
                'success': False,
                'message': 'Missing image data or person name'
            }), 400
        
        if not face_system:
            return jsonify({
                'success': False,
                'message': 'AWS Rekognition not available'
            }), 500
        
        # Decode base64 image
        if ',' in image_data:
            image_bytes = base64.b64decode(image_data.split(',')[1])
        else:
            image_bytes = base64.b64decode(image_data)
        
        # Ensure collection exists
        face_system.create_collection(COLLECTION_ID)
        
        # Check if this person already exists in the collection
        try:
            existing_faces = face_system.list_faces_in_collection(COLLECTION_ID)
            existing_person = None
            for face in existing_faces:
                if face.get('ExternalImageId') == person_name:
                    existing_person = face
                    break
            
            if existing_person:
                return jsonify({
                    'success': True,
                    'facesIndexed': 1,
                    'faceId': existing_person['FaceId'],
                    'message': f'{person_name} already exists in collection, using existing face'
                })
        except Exception as e:
            print(f"Error checking existing faces: {e}")
            # Continue with enrollment if we can't check existing faces
        
        # Generate S3 filename
        s3_filename = f"{person_name}_{int(time.time())}.jpg"
        
        # Upload to S3
        if not upload_to_s3(image_bytes, s3_filename):
            return jsonify({
                'success': False,
                'message': 'Failed to upload image to S3'
            }), 500
        
        # Add face to collection
        faces_indexed = face_system.add_faces_to_collection(
            BUCKET_NAME,
            s3_filename,
            COLLECTION_ID,
            person_name
        )
        
        return jsonify({
            'success': faces_indexed > 0,
            'facesIndexed': faces_indexed,
            'faceId': f"{person_name}_{int(time.time())}" if faces_indexed > 0 else None,
            'message': f'Successfully enrolled {person_name}' if faces_indexed > 0 else 'No faces detected'
        })
        
    except Exception as e:
        print(f"Error in enroll_face: {e}")
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500
    finally:
        # Clean up temporary S3 file after enrollment
        if s3_filename:
            cleanup_s3_file(s3_filename)

@app.route('/api/enrolled-people', methods=['GET'])
def get_enrolled_people():
    """Get list of enrolled people from the collection"""
    try:
        if not face_system:
            return jsonify({
                'success': False,
                'message': 'AWS Rekognition not available'
            }), 500
        
        # List faces in collection
        faces = face_system.list_faces_in_collection(COLLECTION_ID)
        
        # Group faces by ExternalImageId (person name) and get the most recent one for each person
        people_map = {}
        for face in faces:
            external_id = face.get('ExternalImageId')
            if external_id and external_id not in people_map:
                people_map[external_id] = {
                    'name': external_id.replace('_', ' '),  # Convert back from normalized name
                    'faceId': face['FaceId'],
                    'enrolledAt': face.get('CreationTimestamp', '').isoformat() if face.get('CreationTimestamp') else None
                }
        
        enrolled_people = list(people_map.values())
        
        return jsonify({
            'success': True,
            'enrolledPeople': enrolled_people
        })
        
    except Exception as e:
        print(f"Error getting enrolled people: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to fetch enrolled people'
        }), 500

@app.route('/api/recognize-face', methods=['POST'])
def recognize_face():
    s3_filename = None
    try:
        data = request.json
        image_data = data.get('imageData')  # Base64 encoded image
        threshold = data.get('threshold', 80.0)
        
        if not image_data:
            return jsonify({
                'success': False,
                'message': 'Missing image data'
            }), 400
        
        if not face_system:
            return jsonify({
                'success': False,
                'message': 'AWS Rekognition not available'
            }), 500
        
        # Decode base64 image
        if ',' in image_data:
            image_bytes = base64.b64decode(image_data.split(',')[1])
        else:
            image_bytes = base64.b64decode(image_data)
        
        # Generate S3 filename
        s3_filename = f"test_{int(time.time())}.jpg"
        
        # Upload to S3
        if not upload_to_s3(image_bytes, s3_filename):
            return jsonify({
                'success': False,
                'message': 'Failed to upload image to S3'
            }), 500
        
        # Search for faces
        matches = face_system.search_faces_by_image(
            BUCKET_NAME,
            s3_filename,
            COLLECTION_ID,
            threshold
        )
        
        # Format matches
        formatted_matches = []
        for match in matches:
            formatted_matches.append({
                'faceId': match['Face']['FaceId'],
                'externalImageId': match['Face']['ExternalImageId'],
                'similarity': match['Similarity'],
                'confidence': match['Face']['Confidence']
            })
        
        return jsonify({
            'success': True,
            'matches': formatted_matches,
            'message': 'Face recognition completed'
        })
        
    except Exception as e:
        print(f"Error in recognize_face: {e}")
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500
    finally:
        # Clean up temporary S3 file after recognition
        if s3_filename:
            cleanup_s3_file(s3_filename)

@app.route('/api/health', methods=['GET'])
def health_check():
    print("Received health check request")
    return jsonify({
        'status': 'healthy',
        'rekognition_available': face_system is not None,
        'bucket': BUCKET_NAME,
        'region': REGION,
        'collection': COLLECTION_ID
    })

if __name__ == '__main__':
    print("Starting Flask backend server...")
    print(f"Configuration:")
    print(f"  Bucket: {BUCKET_NAME}")
    print(f"  Profile: {PROFILE_NAME}")
    print(f"  Region: {REGION}")
    print(f"  Collection: {COLLECTION_ID}")
    print(f"  Rekognition available: {face_system is not None}")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
