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

export interface EnrolledPerson {
  name: string;
  imageUri: string;
  enrolledAt: Date | null;
}

export interface EnrolledPeopleResult {
  success: boolean;
  enrolledPeople: EnrolledPerson[];
  message?: string;
}

export interface RecognitionResult {
  success: boolean;
  matches: FaceMatch[];
  message?: string;
}


class FaceRecognitionService {
  private backendUrl: string;

  constructor() {
    this.backendUrl = 'http://localhost:5001';// process.env.EXPO_PUBLIC_BACKEND_URL || 'http://localhost:8081';
  }

  private async imageUriToBase64(imageUri: string): Promise<string> {
    try {
      if (imageUri.startsWith('data:')) {
        // If it's already a data URL, extract the base64 part
        return imageUri.split(',')[1];
      } else {
        // Handle blob URLs and regular URLs
        const response = await fetch(imageUri);
        const blob = await response.blob();
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const result = reader.result as string;
            resolve(result.split(',')[1]);
          };
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      }
    } catch (error) {
      console.error('Error converting image to base64:', error);
      throw new Error('Failed to process image');
    }
  }

  async enrollFace(imageUri: string, personName: string, selectedMode: string): Promise<EnrollmentResult> {
    try {
      const imageData = await this.imageUriToBase64(imageUri);
      
      const response = await fetch(`${this.backendUrl}/api/enroll-face`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imageData,
          selectedMode,
          personName,
        }),
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.message || 'Failed to enroll face');
      }

      return result;
    } catch (error) {
      console.error('Error enrolling face:', error);
      return {
        success: false,
        facesIndexed: 0,
        message: 'Failed to enroll face. Please try again.',
      };
    }
  }

  async recognizeFace(imageUri: string, threshold: number = 80.0, method: 'rekognition' | 'human' = 'rekognition'): Promise<RecognitionResult> {
    try {
      const imageData = await this.imageUriToBase64(imageUri);
      
      const response = await fetch(`${this.backendUrl}/api/recognize-face`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imageData,
          threshold,
          facial_recognition_method: method,
        }),
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.message || 'Failed to recognize face');
      }

      return result;
    } catch (error) {
      console.error('Error recognizing face:', error);
      return {
        success: false,
        matches: [],
        message: 'Failed to recognize face. Please try again.',
      };
    }
  }

  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.backendUrl}/api/health`);
      const result = await response.json();
      return response.ok && result.rekognition_available;
    } catch (error) {
      console.error('Health check failed:', error);
      return false;
    }
  }

  async getEnrolledPeople(): Promise<EnrolledPeopleResult> {
    try {
      const response = await fetch(`${this.backendUrl}/api/enrolled-people`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.message || 'Failed to fetch enrolled people');
      }

      return result;
    } catch (error) {
      console.error('Error fetching enrolled people:', error);
      return {
        success: false,
        enrolledPeople: [],
        message: 'Failed to fetch enrolled people. Please try again.',
      };
    }
  }
}

export default new FaceRecognitionService();