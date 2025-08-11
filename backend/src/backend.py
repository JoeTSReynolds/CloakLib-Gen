#!/usr/bin/env python3
"""
backend.py - Flask backend that uses AWS Rekognition and the local Human server.
On enroll: uploads to S3 + Rekognition, saves a local copy to ../images and tells Human to enroll it.
On recognize: accepts facial_recognition_method ("rekognition" or "human") and calls the right backend.
"""

import os
import sys
import subprocess
import signal
import atexit
import time
import base64
import shutil
from wsgiref.simple_server import make_server
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import boto3

load_dotenv()

app = Flask(__name__)
CORS(app)

# Config
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', 'cloakingbucket')
PROFILE_NAME = os.getenv('AWS_PROFILE_NAME', 'default')
REGION = os.getenv('AWS_REGION', 'eu-west-2')
COLLECTION_ID = os.getenv('COLLECTION_ID', 'my-face-collection')

BASE_DIR = Path(__file__).parent
IMAGES_DIR = (BASE_DIR / "../images").resolve()
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Human server
HUMAN_DIR = (BASE_DIR / "../human").resolve()
NODE_SERVER_PATH = (HUMAN_DIR / "human.js").resolve()
HUMAN_PORT = int(os.environ.get('HUMAN_PORT', 5002))
HUMAN_SERVER_URL = f"http://localhost:{HUMAN_PORT}"

node_process = None

# Initialize face_system (Rekognition wrapper)
face_system = None
try:
    # replace with your actual FaceRecognitionSystem class
    from rekognition_system import FaceRecognitionSystem
    face_system = FaceRecognitionSystem(PROFILE_NAME, REGION)
    print(f"[PY] Rekognition initialized")
except Exception as e:
    print(f"[PY] Rekognition init failed (continuing, Rekognition routes will error): {e}")

def start_human_server():
    """Start the node human server as a child process and stream its output to this process stdout/stderr."""
    global node_process

    if not NODE_SERVER_PATH.exists():
        print(f"[PY] human.js not found at {NODE_SERVER_PATH}. Please place human.js there.")
        return

    print("[PY] Starting Human node server...")
    node_env = os.environ.copy()
    node_env['PORT'] = str(HUMAN_PORT)
    node_process = subprocess.Popen(
        ["node", str(NODE_SERVER_PATH)],
        cwd=str(HUMAN_DIR),
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=node_env
    )
    print(f"[PY] Human server started (pid {node_process.pid})")

    def _cleanup():
        print("[PY] Stopping Human server...")
        try:
            if node_process and node_process.poll() is None:
                node_process.terminate()
                try:
                    node_process.wait(timeout=5)
                except Exception:
                    node_process.kill()
        except Exception as e:
            print("[PY] Error stopping node process:", e)

    atexit.register(_cleanup)

    # wait briefly for server to boot, then request sync
    for _ in range(10):
        try:
            r = requests.get(f"{HUMAN_SERVER_URL}/health", timeout=1)
            if r.status_code == 200:
                print("[PY] Human server healthy")
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("[PY] Warning: Human server did not respond to /health")

    # Trigger sync
    try:
        r = requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(IMAGES_DIR)}, timeout=30)
        print("[PY] Human sync response:", r.status_code, r.text)
    except Exception as e:
        print("[PY] Human sync failed:", e)


def upload_to_s3(image_bytes, filename):
    try:
        session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
        s3 = session.client('s3')
        s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_bytes, ContentType='image/jpeg')
        return True
    except Exception as e:
        print("[PY] S3 upload failed:", e)
        return False

def cleanup_s3_file(filename):
    try:
        session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
        s3 = session.client('s3')
        s3.delete_object(Bucket=BUCKET_NAME, Key=filename)
    except Exception as e:
        print("[PY] S3 cleanup failed:", e)

def cloak_image(filename, mode):
    try:
        from fawkes.protection import Fawkes
    except Exception as e:
        print("[PY] fawkes not available:", e)
        return filename

    try:
        fawkes_protector = Fawkes(feature_extractor="arcface_extractor_0", gpu="0", batch_size=5, mode=mode)
        fawkes_protector.run_protection([filename], batch_size=1, format='png', separate_target=True, debug=False, no_align=False)
        cloaked = f"{os.path.splitext(filename)[0]}_cloaked.png"
        return cloaked
    except Exception as e:
        print("[PY] Cloak failed:", e)
        return filename

@app.route('/api/enroll-face', methods=['POST'])
def enroll_face():
    """
    Expects JSON: { imageData: base64, personName: str, selectedMode: "high"|"mid"|"low"|None }
    - uploads to S3, enrolls to Rekognition (if enabled), saves local copy in ../images and calls Human /enroll with local path.
    """
    s3_filename = None
    try:
        data = request.json or {}
        image_data = data.get('imageData')
        person_name = data.get('personName')
        selected_mode = data.get('selectedMode')
        if not image_data or not person_name:
            return jsonify(success=False, message='Missing image data or person name'), 400

        person_key = person_name.replace(' ', '_')

        # decode base64
        if ',' in image_data:
            body = base64.b64decode(image_data.split(',', 1)[1])
        else:
            body = base64.b64decode(image_data)

        # save local file into ../images
        local_filename = f"{person_key}_{int(time.time())}.jpg"
        local_path = IMAGES_DIR / local_filename
        with open(local_path, 'wb') as f:
            f.write(body)

        # cloak if requested
        if selected_mode in ('high', 'mid', 'low'):
            try:
                cloaked_path = cloak_image(str(local_path), selected_mode)
                # overwrite local_path with cloaked image so Human sees the cloaked one
                if os.path.exists(cloaked_path):
                    shutil.copy(cloaked_path, local_path)
            except Exception as e:
                print("[PY] Cloak failed, continuing:", e)

        # upload to S3
        if not upload_to_s3(local_path.read_bytes(), local_filename):
            return jsonify(success=False, message='Failed to upload to S3'), 500

        # ensure Rekognition collection exists & add face
        faces_indexed = 0
        if face_system:
            try:
                face_system.create_collection(COLLECTION_ID)
                faces_indexed = face_system.add_faces_to_collection(BUCKET_NAME, local_filename, COLLECTION_ID, person_key)
            except Exception as e:
                print("[PY] Rekognition enroll error:", e)

        # enroll to Human (send local path)
        try:
            r = requests.post(f"{HUMAN_SERVER_URL}/enroll", json={"name": person_key, "path": str(local_path)}, timeout=30)
            if r.status_code != 200:
                print("[PY] Human enroll responded:", r.status_code, r.text)
        except Exception as e:
            print("[PY] Human enroll failed:", e)

        return jsonify(success=True, facesIndexed=faces_indexed, message=f'Enrolled {person_name}')

    except Exception as e:
        print("[PY] enroll_face error:", e)
        return jsonify(success=False, message='Internal server error'), 500
    finally:
        # Optionally cleanup s3 file if you upload temporary objects you don't want kept
        pass

@app.route('/api/recognize-face', methods=['POST'])
def recognize_face():
    """
    Expects JSON:
      { imageData: base64, facial_recognition_method: "rekognition"|"human", threshold: optional }
    Returns JSON depending on chosen backend.
    """
    try:
        data = request.json or {}
        image_data = data.get('imageData')
        method = (data.get('facial_recognition_method') or 'rekognition').lower()
        threshold = data.get('threshold', 80.0)

        if not image_data:
            return jsonify(success=False, message='Missing image data'), 400

        # decode and save local probe image
        if ',' in image_data:
            body = base64.b64decode(image_data.split(',', 1)[1])
        else:
            body = base64.b64decode(image_data)

        probe_filename = f"probe_{int(time.time())}.jpg"
        probe_path = IMAGES_DIR / probe_filename
        with open(probe_path, 'wb') as f:
            f.write(body)

        if method == 'rekognition':
            if not face_system:
                return jsonify(success=False, message='Rekognition not configured'), 500
            # upload probe temporarily to S3
            upload_to_s3(body, probe_filename)
            matches = []
            try:
                matches = face_system.search_faces_by_image(BUCKET_NAME, probe_filename, COLLECTION_ID, float(threshold))
            except Exception as e:
                print("[PY] Rekognition search error:", e)
            finally:
                cleanup_s3_file(probe_filename)

            # format matches for client
            formatted = []
            for m in matches:
                formatted.append({
                    'faceId': m['Face']['FaceId'],
                    'externalImageId': m['Face'].get('ExternalImageId'),
                    'similarity': m.get('Similarity'),
                    'confidence': m['Face'].get('Confidence')
                })
            return jsonify(success=True, method='rekognition', matches=formatted)

        elif method == 'human':
            try:
                r = requests.post(f"{HUMAN_SERVER_URL}/match", json={"path": str(probe_path), "topk": 5}, timeout=30)
                return jsonify(r.json())
            except Exception as e:
                print("[PY] Human match request failed:", e)
                return jsonify(success=False, message='Human match failed'), 500

        else:
            return jsonify(success=False, message='Invalid facial_recognition_method'), 400

    except Exception as e:
        print("[PY] recognize_face error:", e)
        return jsonify(success=False, message='Internal server error'), 500
    finally:
        # optional: keep probe images or remove them
        try:
            if 'probe_path' in locals() and probe_path.exists():
                probe_path.unlink()
        except Exception:
            pass

if __name__ == '__main__':
    print("[PY] Starting Flask backend (wsgiref server)...")
    # start human server explicitly once
    try:
        start_human_server()
    except Exception as e:
        print('[PY] Failed starting Human server:', e)
    # start simple WSGI server (avoids Werkzeug dev server FD bug in this env)
    try:
        with make_server('0.0.0.0', 5001, app) as httpd:
            print('[PY] Serving on http://0.0.0.0:5001 (no auto-reload)')
            httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[PY] KeyboardInterrupt received, shutting down.')
    except Exception as e:
        print('[PY] Server error:', e)
