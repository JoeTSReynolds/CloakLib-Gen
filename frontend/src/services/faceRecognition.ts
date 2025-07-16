import Constants from 'expo-constants';
import * as FileSystem from 'expo-file-system';

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
  private backendUrl: string;
  private enrolledFaces: { [key: string]: string } = {}; // Store enrolled faces for demo

  constructor() {
    this.bucketName = Constants.expoConfig?.extra?.awsBucketName || process.env.EXPO_PUBLIC_AWS_BUCKET_NAME || '';
    this.profileName = Constants.expoConfig?.extra?.awsProfileName || process.env.EXPO_PUBLIC_AWS_PROFILE_NAME || '';
    this.region = Constants.expoConfig?.extra?.awsRegion || process.env.EXPO_PUBLIC_AWS_REGION || '';
    this.collectionId = Constants.expoConfig?.extra?.collectionId || process.env.EXPO_PUBLIC_COLLECTION_ID || '';
    this.backendUrl = 'http://localhost:5000'; // Backend service URL
  }

  private async convertImageToBase64(imageUri: string): Promise<string> {
    try {
      const base64 = await FileSystem.readAsStringAsync(imageUri, { encoding: FileSystem.EncodingType.Base64 });
      return `data:image/jpeg;base64,${base64}`;
    } catch (error) {
      console.error('Error converting image to base64:', error);
      throw error;
    }
  }

  // Real implementation (requires backend service)
  async enrollFace(imageUri: string, personName: string): Promise<EnrollmentResult> {
    try {
      const imageData = await this.convertImageToBase64(imageUri);
      
      const response = await fetch(`${this.backendUrl}/api/enroll-face`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imageData,
          personName,
          bucketName: this.bucketName,
          collectionId: this.collectionId,
        }),
      });

      const result = await response.json();
      return result;
    } catch (error) {
      console.error('Error enrolling face:', error);
      return {
        success: false,
        facesIndexed: 0,
        message: 'Failed to connect to backend service. Using mock implementation.',
      };
    }
  }

  async recognizeFace(imageUri: string, threshold: number = 80.0): Promise<RecognitionResult> {
    try {
      const imageData = await this.convertImageToBase64(imageUri);
      
      const response = await fetch(`${this.backendUrl}/api/recognize-face`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imageData,
          threshold,
          bucketName: this.bucketName,
          collectionId: this.collectionId,
        }),
      });

      const result = await response.json();
      return result;
    } catch (error) {
      console.error('Error recognizing face:', error);
      return {
        success: false,
        matches: [],
        message: 'Failed to connect to backend service. Using mock implementation.',
      };
    }
  }

  // Mock implementation for demo purposes
  async enrollFaceMock(imageUri: string, personName: string): Promise<EnrollmentResult> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    // Store the enrolled face
    this.enrolledFaces[personName] = imageUri;
    
    return {
      success: true,
      facesIndexed: 1,
      faceId: 'mock-face-id-' + Date.now(),
      message: `Successfully enrolled ${personName}`,
    };
  }

  async recognizeFaceMock(imageUri: string, threshold: number = 80.0): Promise<RecognitionResult> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    // Mock some recognition results based on enrolled faces
    const mockMatches: FaceMatch[] = [];
    
    // Add some realistic mock matches
    const enrolledNames = Object.keys(this.enrolledFaces);
    if (enrolledNames.length > 0) {
      // Simulate matching with enrolled faces (higher chance of matching)
      enrolledNames.forEach((name, index) => {
        // Higher chance of matching enrolled faces
        const similarity = Math.random() * 30 + 70; // Random similarity between 70-100
        if (similarity >= threshold) {
          mockMatches.push({
            faceId: `mock-face-id-${index}`,
            externalImageId: name,
            similarity: similarity,
            confidence: Math.random() * 10 + 90, // Random confidence between 90-100
          });
        }
      });
      
      // Sometimes add random matches for demo
      if (Math.random() > 0.7) {
        const randomSimilarity = Math.random() * 20 + 60; // 60-80%
        if (randomSimilarity >= threshold) {
          mockMatches.push({
            faceId: 'mock-face-id-random',
            externalImageId: 'Unknown_Person',
            similarity: randomSimilarity,
            confidence: Math.random() * 15 + 85, // 85-100%
          });
        }
      }
    }
    
    // Add some default mock matches if no faces are enrolled
    if (mockMatches.length === 0 && enrolledNames.length === 0) {
      const defaultMatches: FaceMatch[] = [
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
      
      mockMatches.push(...defaultMatches.filter(match => match.similarity >= threshold));
    }

    // Sort by similarity (highest first)
    mockMatches.sort((a, b) => b.similarity - a.similarity);

    return {
      success: true,
      matches: mockMatches,
      message: mockMatches.length > 0 ? 'Face recognition completed' : 'No matches found',
    };
  }

  // Get enrolled faces for display
  getEnrolledFaces(): { [key: string]: string } {
    return { ...this.enrolledFaces };
  }

  // Clear enrolled faces
  clearEnrolledFaces(): void {
    this.enrolledFaces = {};
  }
}

export default new FaceRecognitionService();
