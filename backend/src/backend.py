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

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import boto3
import json
import threading

load_dotenv()

app = Flask(__name__)
CORS(app)

# Config
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', 'cloakingbucket')
PROFILE_NAME = os.getenv('AWS_PROFILE_NAME', 'default')
REGION = os.getenv('AWS_REGION', 'eu-west-2')
COLLECTION_ID = os.getenv('COLLECTION_ID', 'default')

BASE_DIR = Path(__file__).parent
IMAGES_DIR = (BASE_DIR / "../images").resolve()
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
# Datasets base dir (uploaded datasets are expanded/copied here under subfolders)
DATASETS_DIR = (BASE_DIR / "../datasets").resolve()
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# Human server
HUMAN_DIR = (BASE_DIR / "../human").resolve()
NODE_SERVER_PATH = (HUMAN_DIR / "human.js").resolve()
HUMAN_PORT = int(os.environ.get('HUMAN_PORT', 5002))
HUMAN_SERVER_URL = f"http://localhost:{HUMAN_PORT}"

node_process = None

from rekognition_system import FaceRecognitionSystem
face_system = FaceRecognitionSystem(PROFILE_NAME, REGION)
print(f"[PY] Rekognition initialized")

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
        images = face_system.list_faces_in_collection(COLLECTION_ID)
        personNames = []
        for face in images:
            pk = face.get('ExternalImageId')
            if pk:
                personNames.append(pk)
        r = requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(IMAGES_DIR), "personNames": personNames}, timeout=30)
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

def _enroll_face_internal(image_data, person_name, selected_mode=None, face_collection=COLLECTION_ID):
    """
    Internal function to enroll a face. Returns a dictionary instead of Flask response.
    """
    try:
        if not image_data or not person_name:
            return {'success': False, 'message': 'Missing image data or person name'}

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
            return {'success': False, 'message': 'Failed to upload to S3'}

        # ensure Rekognition collection exists & add face
        faces_indexed = 0
        if face_system:
            try:
                face_system.create_collection(face_collection)
                faces_indexed = face_system.add_faces_to_collection(BUCKET_NAME, local_filename, face_collection, person_key)
            except Exception as e:
                print("[PY] Rekognition enroll error:", e)

        # enroll to Human (send local path)
        try:
            r = requests.post(f"{HUMAN_SERVER_URL}/enroll", json={"name": person_key, "path": str(local_path), "datasetName": face_collection}, timeout=30)
            if r.status_code != 200:
                print("[PY] Human enroll responded:", r.status_code, r.text)
        except Exception as e:
            print("[PY] Human enroll failed:", e)

        return {
            'success': True, 
            'facesIndexed': faces_indexed, 
            'message': f'Enrolled {person_name}', 
            'local_filename': local_filename
        }

    except Exception as e:
        print("[PY] _enroll_face_internal error:", e)
        return {'success': False, 'message': 'Internal server error'}

@app.route('/api/enroll-face', methods=['POST'])
def enroll_face():
    """
    Flask route wrapper for _enroll_face_internal
    """
    try:
        data = request.json or {}
        result = _enroll_face_internal(
            image_data=data.get('imageData'),
            person_name=data.get('personName'),
            selected_mode=data.get('selectedMode')
        )
        
        if result['success']:
            return jsonify(result)
        else:
            status_code = 400 if 'Missing' in result.get('message', '') else 500
            return jsonify(result), status_code
            
    except Exception as e:
        print("[PY] enroll_face error:", e)
        return jsonify(success=False, message='Internal server error'), 500


def _iter_local_images(root: Path):
    for p in root.rglob('*'):
        if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
            yield p

@app.route('/api/enroll-dataset', methods=['POST'])
def enroll_dataset():
    """
    Enroll a dataset folder.
    Expects JSON: { datasetName: str, files?: [{ name, data (base64) }] }
    Behavior:
      - Copies (or references) images under DATASETS_DIR/datasetName preserving subfolders
      - For AWS: create a new collection named datasetName and upload images with ExternalImageId = parent folder name
      - For Human: build a separate DB file named f"{datasetName}_faces-db.json" from the dataset folder
    Returns: { success, message, counts: {uploaded, indexed, humanAdded} }
    """
    try:
        data = request.json or {}
        dataset_name = (data.get('datasetName') or '').strip()
        files = data.get('files') or []
        if not dataset_name:
            return jsonify(success=False, message='Missing datasetName'), 40

        copied = 0
        local_filenames = []
        # provided files array (web)
        if isinstance(files, list) and files:
            for f in files:
                try:
                    response_data = _enroll_face_internal(
                        image_data=f.get('data'), 
                        person_name=f.get('name'), 
                        face_collection=dataset_name
                    )

                    if not response_data.get('success'):
                        print('[PY] failed enrolling face:', response_data.get('message'))
                        continue

                    local_filenames.append(response_data.get('local_filename'))
                    copied += 1
                except Exception as e:
                    print('[PY] failed writing dataset file:', e)
        else:
            return jsonify(success=False, message='Provide either localFolder or files[]'), 400

        # AWS: create collection and upload/index
        uploaded = 0
        indexed = 0
        if face_system:
            session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
            s3 = session.client('s3')
            for filename in local_filenames:
                # ExternalImageId from filename, trimming _<digits> suffix
                stem = os.path.splitext(filename)[0]
                # normalize like Human: remove trailing _<digits>
                import re
                m = re.match(r'^(.*?)(?:_\d+)?$', stem)
                person = (m.group(1) if m else stem)
                if "cloaked" in person.split("_"):
                    person = "_".join(person.split("_")[:-2])
                key = f"{dataset_name}/{person}/{filename}"
                img_path = os.path.join(IMAGES_DIR, filename)
                try:
                    with open(img_path, 'rb') as f:
                        img_bytes = f.read()
                    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=img_bytes, ContentType='image/jpeg')
                    uploaded += 1
                    # index into collection named dataset_name
                    try:
                        # we must pass S3 object path: re-uploaded key above
                        res = face_system.add_faces_to_collection(BUCKET_NAME, key, dataset_name, person)
                        indexed += int(res or 0)
                    except Exception as e:
                        print('[PY] Rekognition index error for', key, e)
                except Exception as e:
                    print('[PY] S3 put error for', key, e)

        return jsonify(success=True, message=f'Enrolled dataset {dataset_name}', counts={"copied": copied, "uploaded": uploaded, "indexed": indexed})
    except Exception as e:
        print('[PY] enroll_dataset error:', e)
        return jsonify(success=False, message='Internal server error'), 500

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
                raw = r.json()
                human_matches = raw.get('matches', []) if isinstance(raw, dict) else []
                normalized = []
                for m in human_matches:
                    # human similarity likely 0..1; convert to percentage if so
                    sim = m.get('similarity')
                    if isinstance(sim, (int, float)) and sim <= 1.0:
                        sim_pct = sim * 100.0
                    else:
                        sim_pct = sim
                    normalized.append({
                        'faceId': m.get('filename'),
                        'externalImageId': m.get('name'),
                        'similarity': sim_pct,
                        'confidence': None
                    })
                print(normalized)
                return jsonify(success=True, method='human', matches=normalized)
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

_HUMAN_DB_SYNCED = False
_SYNC_LOCK = threading.Lock()

def _download_images_from_s3_if_needed():
    """Download only the images that belong to the Rekognition collection from S3 into IMAGES_DIR.
    Strategy:
      - List faces in the collection -> get unique ExternalImageId values (person keys)
      - For each person key P, list S3 objects with Prefix=f"{P}_" (the naming pattern used at enrollment)
      - Download any that are missing locally
    Runs only once per process lifetime to avoid repeated S3 calls.
    Returns True if a sync (any S3 listing) happened this call, False otherwise.
    """
    global _HUMAN_DB_SYNCED
    if _HUMAN_DB_SYNCED:
        return False
    with _SYNC_LOCK:
        if _HUMAN_DB_SYNCED:
            return False
        print('[PY] Performing one-time targeted S3 -> local image sync (collection members only)...')
        try:
            session = boto3.Session(profile_name=PROFILE_NAME, region_name=REGION)
            s3 = session.client('s3')
            # Gather person keys from Rekognition collection
            person_keys = set()
            if face_system:
                try:
                    faces = face_system.list_faces_in_collection(COLLECTION_ID) or []
                    for face in faces:
                        pk = face.get('ExternalImageId')
                        if pk:
                            person_keys.add(pk)
                except Exception as e:
                    print('[PY] Rekognition list during sync failed:', e)

            if not person_keys:
                print('[PY] No faces found in collection; skipping S3 download phase.')
                _HUMAN_DB_SYNCED = True
                return True

            count_downloaded = 0
            for pk in sorted(person_keys):
                prefix = f"{pk}_"
                continuation_token = None
                while True:
                    kwargs = {'Bucket': BUCKET_NAME, 'Prefix': prefix, 'MaxKeys': 1000}
                    if continuation_token:
                        kwargs['ContinuationToken'] = continuation_token
                    resp = s3.list_objects_v2(**kwargs)
                    for obj in resp.get('Contents', []):
                        key = obj['Key']
                        if key.endswith('/'):
                            continue
                        local_path = IMAGES_DIR / key
                        if not local_path.exists():
                            try:
                                s3.download_file(BUCKET_NAME, key, str(local_path))
                                count_downloaded += 1
                            except Exception as e:
                                print(f'[PY] Failed downloading {key}:', e)
                    if resp.get('IsTruncated'):
                        continuation_token = resp.get('NextContinuationToken')
                    else:
                        break
            print(f'[PY] Targeted S3 sync complete. Downloaded {count_downloaded} new objects across {len(person_keys)} person prefixes.')
            _HUMAN_DB_SYNCED = True
            # After syncing images, tell Human server to rebuild DB
            try:
                r = requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(IMAGES_DIR)}, timeout=60)
                print('[PY] Post-sync Human /sync-db response:', r.status_code)
            except Exception as e:
                print('[PY] Post-sync Human sync-db failed:', e)
            return True
        except Exception as e:
            print('[PY] S3 sync error:', e)
            return False

def _collect_people_with_images():
    """Aggregate people data from Human DB and Rekognition (names) and attach base64 image data.
    Preference order for selecting an image: first listed Human image, otherwise first local file matching name_*."""
    people = {}
    # Human DB
    try:
        db_path = (HUMAN_DIR / 'faces-db.json').resolve()
        if db_path.exists():
            with open(db_path, 'r') as f:
                db = json.load(f)
            for name, entry in (db.get('people') or {}).items():
                images = entry.get('images') or []
                enrolled_at = entry.get('enrolledAt')
                img_path = None
                for cand in images:
                    p = Path(cand)
                    if p.exists():
                        img_path = p
                        break
                people.setdefault(name, { 'name': name, 'imagePath': str(img_path) if img_path else None, 'enrolledAt': enrolled_at })
    except Exception as e:
        print('[PY] enrolled_people: failed reading human DB:', e)

    # Rekognition list (names only if missing)
    if face_system:
        try:
            faces = face_system.list_faces_in_collection(COLLECTION_ID) or []
            for face in faces:
                name = face.get('ExternalImageId') or 'Unknown'
                people.setdefault(name, { 'name': name, 'imagePath': None, 'enrolledAt': None })
        except Exception as e:
            print('[PY] enrolled_people: rekognition list error:', e)

    # For any person without imagePath, try to find a local file by prefix
    for pdata in people.values():
        if not pdata.get('imagePath'):
            prefix = pdata['name'] + '_'
            matches = sorted([p for p in IMAGES_DIR.glob(prefix + '*') if p.is_file()], reverse=True)
            if matches:
                pdata['imagePath'] = str(matches[0])

    # Convert to API shape with base64 imageUri
    api_people = []
    for pdata in people.values():
        image_uri = None
        ipath = pdata.get('imagePath')
        if ipath and os.path.exists(ipath):
            try:
                with open(ipath, 'rb') as f:
                    b = f.read()
                b64 = base64.b64encode(b).decode('utf-8')
                # assume jpeg if extension .jpg/.jpeg else png
                ext = os.path.splitext(ipath)[1].lower()
                mime = 'image/png' if ext == '.png' else 'image/jpeg'
                image_uri = f'data:{mime};base64,{b64}'
            except Exception as e:
                print('[PY] Failed reading image for person', pdata['name'], e)
        api_people.append({
            'name': pdata['name'],
            'imageUri': image_uri,
            'enrolledAt': pdata.get('enrolledAt')
        })

    return sorted(api_people, key=lambda x: x['name'].lower())

@app.route('/api/enrolled-people', methods=['GET'])
def enrolled_people():
    """Return enrolled people.
    If query param datasetName is provided, return people from that dataset (Human DB + local dataset images).
    Otherwise, default to legacy behavior (S3 collection + default Human DB/images).
    """
    dataset_name = (request.args.get('datasetName') or '').strip()
    if dataset_name:
        # Ensure Human DB for this dataset is synced, then list
        dataset_dir = (DATASETS_DIR / dataset_name).resolve()
        try:
            requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(dataset_dir), "datasetName": dataset_name}, timeout=60)
        except Exception as e:
            print('[PY] dataset enrolled-people: human sync failed:', e)
        # pull list from human
        try:
            r = requests.get(f"{HUMAN_SERVER_URL}/list-enrolled", params={"datasetName": dataset_name}, timeout=30)
            raw = r.json()
            images = raw.get('images', []) if isinstance(raw, dict) else []
        except Exception as e:
            print('[PY] dataset list-enrolled failed:', e)
            images = []
        # Group by name and pick first image for preview
        people = {}
        for it in images:
            name = it.get('name') or 'Unknown'
            img_path = it.get('path')
            people.setdefault(name, img_path)
        api_people = []
        for name, ipath in people.items():
            image_uri = None
            if ipath and os.path.exists(ipath):
                try:
                    with open(ipath, 'rb') as f:
                        b = f.read()
                    b64 = base64.b64encode(b).decode('utf-8')
                    ext = os.path.splitext(ipath)[1].lower()
                    mime = 'image/png' if ext == '.png' else 'image/jpeg'
                    image_uri = f'data:{mime};base64,{b64}'
                except Exception as e:
                    print('[PY] dataset enrolled-people read image failed:', e)
            api_people.append({ 'name': name, 'imageUri': image_uri, 'enrolledAt': None })
        return jsonify(success=True, enrolledPeople=sorted(api_people, key=lambda x: x['name'].lower()), performedInitialSync=False)

    # Legacy/default path using collection and default Human DB
    did_sync = _download_images_from_s3_if_needed()
    if not did_sync:
        try:
            r = requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(IMAGES_DIR)}, timeout=30)
            if r.status_code != 200:
                print('[PY] Human quick sync-db non-200:', r.status_code)
        except Exception as e:
            print('[PY] Human quick sync-db failed:', e)

    enrolled_list = _collect_people_with_images()
    return jsonify(success=True, enrolledPeople=enrolled_list, performedInitialSync=did_sync)

def _human_list_enrolled(dataset_name: str):
    try:
        r = requests.get(f"{HUMAN_SERVER_URL}/list-enrolled", params={"datasetName": dataset_name}, timeout=30)
        raw = r.json()
        return raw.get('images', []) if isinstance(raw, dict) else []
    except Exception as e:
        print('[PY] human list-enrolled failed:', e)
        return []

@app.route('/api/batch-recognize', methods=['POST'])
def batch_recognize():
    """
        Expects JSON: {
            datasetName: str,            # enrolled dataset/collection to use
            probeFolder?: str,           # local folder of images to evaluate
            files?: [{ name, data(base64) }], # web-uploaded probes
            humanThreshold?: float,
            rekognitionThreshold?: float
        }
    Returns JSON with CSV content and a filename to download.
    """
    try:
        data = request.json or {}
        dataset_name = (data.get('datasetName') or '').strip()
        probe_folder = data.get('probeFolder') or data.get('probefolder') or data.get('localFolder')
        files = data.get('files') or []
        human_threshold = float(data.get('humanThreshold', 0.6))
        rek_threshold = float(data.get('rekognitionThreshold', 80.0))
        if not dataset_name:
            return jsonify(success=False, message='Missing datasetName'), 400

        print(f'[PY] Starting batch recognition for dataset: {dataset_name}')
        print(f'[PY] Number of probe files: {len(files) if isinstance(files, list) else 0}')

        tmp_dir = None
        # Prepare probe_dir from either local folder or uploaded files
        if probe_folder and isinstance(probe_folder, str) and len(probe_folder.strip()) > 0:
            probe_dir = Path(probe_folder).resolve()
            if not probe_dir.exists() or not probe_dir.is_dir():
                return jsonify(success=False, message=f'Probe folder not found: {probe_dir}'), 400
        elif isinstance(files, list) and files:
            # create temp folder
            out_dir = (BASE_DIR / '../tmp-batch').resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp_dir = out_dir / f"{dataset_name}_{int(time.time())}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            probe_dir = tmp_dir
            print(f'[PY] Created temp directory: {tmp_dir}')
        else:
            return jsonify(success=False, message='Provide either probeFolder or files[]'), 400

        # Collect enrolled images for Human (to use its embeddings db)
        dataset_dir = (DATASETS_DIR / dataset_name).resolve()
        # ensure Human DB is synced for this dataset
        try:
            requests.post(f"{HUMAN_SERVER_URL}/sync-db", json={"imagesDir": str(dataset_dir), "datasetName": dataset_name}, timeout=120)
        except Exception as e:
            print('[PY] human pre-sync for batch failed:', e)

        rows = []
        # Process each uploaded file directly (similar to dataset enrollment)
        if isinstance(files, list) and files:
            for f in files:
                try:
                    img_name = f.get('name') or f"probe_{int(time.time()*1000)}.jpg"
                    data_b64 = f.get('data')
                    if not data_b64:
                        continue
                    
                    print(f'[PY] Processing probe image: {img_name}')
                    
                    # Prepare image data for recognition calls (similar to recognizeFace endpoint)
                    if isinstance(data_b64, str) and ',' in data_b64:
                        image_data = data_b64.split(',', 1)[1]
                    else:
                        image_data = data_b64

                    # Human match - call recognition like the single recognition endpoint
                    human_sim = 0.0
                    human_match = None
                    try:
                        # Save temp file for Human recognition (it needs file path)
                        temp_file = tmp_dir / f"temp_{img_name}"
                        temp_file.write_bytes(base64.b64decode(image_data))
                        
                        # Just match against the dataset (don't enroll the probe)
                        hr = requests.post(f"{HUMAN_SERVER_URL}/match", json={
                            "path": str(temp_file), 
                            "threshold": human_threshold, 
                            "topk": 1, 
                            "datasetName": dataset_name, 
                            "imagesDir": str(dataset_dir)
                        }, timeout=60)
                        
                        if hr.status_code == 200:
                            hraw = hr.json()
                            hmatches = (hraw or {}).get('matches', [])
                            if hmatches:
                                htop = hmatches[0]
                                sim = htop.get('similarity')
                                if isinstance(sim, (int, float)) and sim <= 1.0:
                                    sim = sim * 100.0
                                human_sim = float(sim or 0.0)
                                human_match = htop.get('filename') or htop.get('name')
                        
                        # Clean up temp file
                        if temp_file.exists():
                            temp_file.unlink()
                            
                    except Exception as e:
                        print('[PY] human match error:', e)

                    # Rekognition match - use the existing recognition system
                    rek_sim = 0.0
                    rek_match = None
                    if face_system:
                        try:
                            # Upload probe image to S3 temporarily
                            temp_s3_key = f"temp_probe_{int(time.time()*1000)}_{img_name}"
                            buf = base64.b64decode(image_data)
                            upload_to_s3(buf, temp_s3_key)
                            
                            # Search in the dataset collection
                            matches = face_system.search_faces_by_image(BUCKET_NAME, temp_s3_key, dataset_name, rek_threshold)
                            
                            if matches:
                                m = matches[0]
                                rek_sim = float(m.get('Similarity') or 0.0)
                                rek_match = (m.get('Face') or {}).get('ExternalImageId')
                                
                        except Exception as e:
                            print('[PY] Rekognition batch search error:', e)
                        finally:
                            try:
                                cleanup_s3_file(temp_s3_key)
                            except Exception:
                                pass

                    rows.append([img_name, f"{rek_sim:.2f}%" if rek_sim else '0%', rek_match or 'null', f"{human_sim:.2f}%" if human_sim else '0%', human_match or 'null'])
                    print(f'[PY] Processed {img_name}: Rek={rek_sim:.2f}%, Human={human_sim:.2f}%')
                    
                except Exception as e:
                    print(f'[PY] Error processing file {f.get("name", "unknown")}: {e}')
                    # Still add a row with errors
                    rows.append([f.get('name', 'error'), 'error', 'error', 'error', 'error'])

        # Build CSV
        print(f'[PY] Building CSV with {len(rows)} rows')
        csv_lines = ["Image Name,Rekognition Similarity,Rekognition matched image,Human similarity,Human matched image"]
        for r in rows:
            # escape commas in names if present
            safe = [str(x).replace('\n', ' ').replace(',', ';') for x in r]
            csv_lines.append(','.join(safe))
        csv_content = '\n'.join(csv_lines)
        
        print(f'[PY] CSV content preview (first 200 chars): {csv_content[:200]}...')

        # Save a temp CSV file
        out_dir = (BASE_DIR / '../batch-results').resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"batch_{dataset_name}_{int(time.time())}.csv"
        out_path.write_text(csv_content, encoding='utf-8')
        print(f'[PY] CSV saved to: {out_path}')

        # Cleanup temp dir if created
        try:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
                print(f'[PY] Cleaned up temp directory: {tmp_dir}')
        except Exception:
            pass

        return jsonify(success=True, csvPath=str(out_path), csv=csv_content)
    except Exception as e:
        print('[PY] batch_recognize error:', e)
        return jsonify(success=False, message='Internal server error'), 500

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
