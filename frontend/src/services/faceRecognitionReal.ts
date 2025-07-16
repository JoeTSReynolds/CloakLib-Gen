import * as FileSystem from 'expo-file-system';
import { FaceRecognitionSystem } from '../../Cloak-Comparison/fawkes_rekognition_test';

export interface FaceMatch {
  faceId: string;
  externalImageId: string;
  similarity: number;
  confidence: number;
}

export interface EnrollmentResult {
  success: boolean;
  facesIndexed: number;
  faceId?: string;
  message?: string;
}

export interface RecognitionResult {
  success: boolean;
  matches: FaceMatch[];
  message?: string;
}

class FaceRecognitionService {
  private bucketName: string;
  private profileName: string;
  private region: string;
  private collectionId: string;
  private rekognitionSystem: FaceRecognitionSystem | null = null;

  constructor() {
    this.bucketName = process.env.EXPO_PUBLIC_AWS_BUCKET_NAME || '';
    this.profileName = process.env.EXPO_PUBLIC_AWS_PROFILE_NAME || '';
    this.region = process.env.EXPO_PUBLIC_AWS_REGION || '';
    this.collectionId = process.env.EXPO_PUBLIC_COLLECTION_ID || '';
    
    try {
      this.rekognitionSystem = new FaceRecognitionSystem(this.profileName, this.region);
    } catch (error) {
      console.error('Error initializing AWS Rekognition:', error);
    }
  }

  private async uploadImageToS3(imageUri: string, filename: string): Promise<boolean> {
    try {
      // In a real implementation, you would upload the image to S3
      // For now, we'll assume the image is already in S3 or use mock data
      console.log(`Mock upload of ${filename} to S3`);
      return true;
    } catch (error) {
      console.error('Error uploading to S3:', error);
      return false;
    }
  }

  async enrollFace(imageUri: string, personName: string): Promise<EnrollmentResult> {
    try {
      if (!this.rekognitionSystem) {
        throw new Error('AWS Rekognition not initialized');
      }

      // Generate a unique filename
      const filename = `${personName}_${Date.now()}.jpg`;
      
      // Upload image to S3 (mock implementation)
      const uploadSuccess = await this.uploadImageToS3(imageUri, filename);
      if (!uploadSuccess) {
        throw new Error('Failed to upload image to S3');
      }

      // Ensure collection exists
      await this.rekognitionSystem.create_collection(this.collectionId);

      // Add face to collection
      const facesIndexed = await this.rekognitionSystem.add_faces_to_collection(
        this.bucketName,
        filename,
        this.collectionId,
        personName
      );

      return {
        success: facesIndexed > 0,
        facesIndexed,
        message: facesIndexed > 0 ? `Successfully enrolled ${personName}` : 'No faces detected in image',
      };
    } catch (error) {
      console.error('Error enrolling face:', error);
      return {
        success: false,
        facesIndexed: 0,
        message: 'Failed to enroll face. Please try again.',
      };
    }
  }

  async recognizeFace(imageUri: string, threshold: number = 80.0): Promise<RecognitionResult> {
    try {
      if (!this.rekognitionSystem) {
        throw new Error('AWS Rekognition not initialized');
      }

      // Generate a unique filename
      const filename = `test_${Date.now()}.jpg`;
      
      // Upload image to S3 (mock implementation)
      const uploadSuccess = await this.uploadImageToS3(imageUri, filename);
      if (!uploadSuccess) {
        throw new Error('Failed to upload image to S3');
      }

      // Search for faces
      const matches = await this.rekognitionSystem.search_faces_by_image(
        this.bucketName,
        filename,
        this.collectionId,
        threshold
      );

      const formattedMatches: FaceMatch[] = matches.map(match => ({
        faceId: match.Face.FaceId,
        externalImageId: match.Face.ExternalImageId,
        similarity: match.Similarity,
        confidence: match.Face.Confidence,
      }));

      return {
        success: true,
        matches: formattedMatches,
        message: formattedMatches.length > 0 ? 'Face recognition completed' : 'No matches found',
      };
    } catch (error) {
      console.error('Error recognizing face:', error);
      return {
        success: false,
        matches: [],
        message: 'Failed to recognize face. Please try again.',
      };
    }
  }

  // Mock implementation for demo purposes
  async enrollFaceMock(imageUri: string, personName: string): Promise<EnrollmentResult> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    return {
      success: true,
      facesIndexed: 1,
      faceId: 'mock-face-id-' + Date.now(),
      message: `Successfully enrolled ${personName}`,
    };
  }

  async recognizeFaceMock(imageUri: string, threshold: number = 80.0): Promise<RecognitionResult> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Mock some recognition results
    const mockMatches: FaceMatch[] = [
      {
        faceId: 'mock-face-id-1',
        externalImageId: 'John_Doe',
        similarity: 95.5,
        confidence: 99.2,
      },
      {
        faceId: 'mock-face-id-2',
        externalImageId: 'Jane_Smith',
        similarity: 87.3,
        confidence: 96.8,
      },
    ];

    return {
      success: true,
      matches: mockMatches.filter(match => match.similarity >= threshold),
      message: mockMatches.length > 0 ? 'Face recognition completed' : 'No matches found',
    };
  }
}

export default new FaceRecognitionService();
