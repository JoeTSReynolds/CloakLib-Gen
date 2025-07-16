# Fawkes vs Rekognition Demo

A React Native Expo application that demonstrates face recognition using AWS Rekognition with a user-friendly interface for enrolling faces and testing recognition.

## Features

- **Face Enrollment**: Upload images and assign person names to build a face collection
- **Face Recognition**: Test images against the enrolled collection with configurable confidence thresholds
- **Real-time Results**: View similarity scores and confidence levels
- **Modern UI**: Clean, responsive design with proper styling
- **Environment Configuration**: Configurable AWS settings via environment variables

## Setup

### Prerequisites

- Node.js (v16 or higher)
- npm or yarn
- Expo CLI (`npm install -g expo-cli`)
- Python 3.7+ (for backend service)
- AWS account with Rekognition access (for real implementation)

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Configure environment variables:
Create a `.env` file in the frontend directory:
```
EXPO_PUBLIC_AWS_BUCKET_NAME=your-s3-bucket-name
EXPO_PUBLIC_AWS_PROFILE_NAME=your-aws-profile
EXPO_PUBLIC_AWS_REGION=your-aws-region
EXPO_PUBLIC_COLLECTION_ID=your-collection-id
```

4. Start the development server:
```bash
npm start
```

### Backend Setup (Optional - for real AWS integration)

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Configure AWS credentials:
Make sure you have AWS credentials configured via:
- AWS CLI (`aws configure`)
- AWS credentials file
- Environment variables

3. Set up environment variables:
```bash
export AWS_BUCKET_NAME=your-s3-bucket-name
export AWS_PROFILE_NAME=your-aws-profile
export AWS_REGION=your-aws-region
export COLLECTION_ID=your-collection-id
```

4. Start the backend service:
```bash
python backend_service.py
```

## Usage

### Demo Mode (Mock Implementation)

The app includes a mock implementation that works without AWS setup:

1. **Enroll a Face**:
   - Tap "Select Image to Enroll"
   - Choose an image from your device
   - Enter a person's name
   - Tap "Enroll Face"

2. **Test Recognition**:
   - Tap "Select Image to Test"
   - Choose an image to test
   - Adjust confidence threshold if needed
   - Tap "Recognize Face"
   - View results with similarity scores

### Real AWS Integration

To use real AWS Rekognition:

1. Set up the backend service (see Backend Setup above)
2. Ensure your S3 bucket exists and is accessible
3. Update the service to use `enrollFace` and `recognizeFace` methods instead of the mock versions
4. The backend service will handle image uploads to S3 and AWS Rekognition API calls

## Architecture

### Frontend (React Native + Expo)
- `src/screens/FaceRecognitionScreen.tsx`: Main UI component
- `src/services/faceRecognition.ts`: Service layer for API calls
- `src/services/faceRecognitionReal.ts`: Real AWS integration (requires backend)

### Backend (Python + Flask)
- `backend_service.py`: Flask API for AWS Rekognition integration
- Handles image uploads to S3
- Manages face collection operations
- Performs face recognition queries

## Environment Variables

### Frontend (.env)
```
EXPO_PUBLIC_AWS_BUCKET_NAME=your-s3-bucket-name
EXPO_PUBLIC_AWS_PROFILE_NAME=your-aws-profile
EXPO_PUBLIC_AWS_REGION=your-aws-region
EXPO_PUBLIC_COLLECTION_ID=your-collection-id
```

### Backend
```
AWS_BUCKET_NAME=your-s3-bucket-name
AWS_PROFILE_NAME=your-aws-profile
AWS_REGION=your-aws-region
COLLECTION_ID=your-collection-id
```
