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

# Add the parent directory to Python path to import the FaceRecognitionSystem
sys.path.append(str(Path(__file__).parent.parent))

try:
    # Try to import from parent directory
    sys.path.append(str(Path(__file__).parent.parent / "Cloak-Comparison"))
    from fawkes_rekognition_test import FaceRecognitionSystem
except ImportError:
    try:
        # Try alternative import path
        sys.path.append(str(Path(__file__).parent.parent))
        from fawkes_rekognition_test import FaceRecognitionSystem
    except ImportError:
        print("Warning: Could not import FaceRecognitionSystem. Using mock implementation.")
        FaceRecognitionSystem = None

app = Flask(__name__)
CORS(app)

# Configuration from environment variables
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', 'cloakingbucketdoubleday')
PROFILE_NAME = os.getenv('AWS_PROFILE_NAME', 'joe')
REGION = os.getenv('AWS_REGION', 'eu-west-2')
COLLECTION_ID = os.getenv('COLLECTION_ID', 'my-face-collection')

# Initialize face recognition system
face_system = None
if FaceRecognitionSystem:
    try:
        face_system = FaceRecognitionSystem(PROFILE_NAME, REGION)
        print(f"Initialized AWS Rekognition with profile: {PROFILE_NAME}, region: {REGION}")
    except Exception as e:
        print(f"Error initializing AWS Rekognition: {e}")

def upload_to_s3(image_bytes, filename):
    """Upload image bytes to S3 bucket"""
    try:
        s3_client = boto3.client('s3', region_name=REGION)
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

@app.route('/api/enroll-face', methods=['POST'])
def enroll_face():
    try:
        data = request.json
        image_data = data.get('imageData')  # Base64 encoded image
        person_name = data.get('personName')
        
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
        
        # Generate S3 filename
        s3_filename = f"{person_name}_{int(time.time())}.jpg"
        
        # Upload to S3
        if not upload_to_s3(image_bytes, s3_filename):
            return jsonify({
                'success': False,
                'message': 'Failed to upload image to S3'
            }), 500
        
        # Ensure collection exists
        face_system.create_collection(COLLECTION_ID)
        
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
            'message': f'Successfully enrolled {person_name}' if faces_indexed > 0 else 'No faces detected'
        })
        
    except Exception as e:
        print(f"Error in enroll_face: {e}")
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500

@app.route('/api/recognize-face', methods=['POST'])
def recognize_face():
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

@app.route('/api/health', methods=['GET'])
def health_check():
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
