export interface FaceMatch {
  faceId: string;
  externalImageId: string;
  similarity: number; // percentage (0-100)
  confidence: number | null; // Rekognition provides confidence; human backend sets null
}

export interface EnrollmentResult {
  success: boolean;
  facesIndexed: number;
  faceId?: string;
  message?: string;
}

export interface EnrolledPerson {
  name: string;
  imageUri: string | null;
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

export interface DatasetFile {
  name: string;
  data: string; // base64 without data: prefix
}

export interface EnrollDatasetResult {
  success: boolean;
  message?: string;
  counts?: { copied?: number; uploaded?: number; indexed?: number; humanTotal?: number };
}

export interface BatchRecognizeResult {
  success: boolean;
  csv?: string;
  csvPath?: string;
  message?: string;
}


class FaceRecognitionService {
  private backendUrl: string;

  constructor() {
  const envUrl = (process.env as any)?.EXPO_PUBLIC_BACKEND_URL as string | undefined;
  this.backendUrl = envUrl && envUrl.length > 0 ? envUrl : 'http://localhost:5001';
  }

  private async imageUriToBase64(imageUri: string): Promise<string> {
    try {
      if (imageUri.startsWith('data:')) {
        // If it's already a data URL, extract the base64 part
        return imageUri.split(',')[1];
      } else {
        // Handle blob URLs and file:// URIs across platforms
        try {
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
        } catch (e) {
          // Fallback for Expo file system URIs
          // @ts-ignore: dynamic import to avoid heavy dependency when unused
          const FileSystem = await import('expo-file-system');
          const base64 = await FileSystem.readAsStringAsync(imageUri, { encoding: FileSystem.EncodingType.Base64 });
          return base64;
        }
      }
    } catch (error) {
      console.error('Error converting image to base64:', error, imageUri);
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

  async enrollDataset(datasetName: string, files: DatasetFile[]): Promise<EnrollDatasetResult> {
    try {
      const response = await fetch(`${this.backendUrl}/api/enroll-dataset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datasetName, files }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Failed to enroll dataset');
      return result;
    } catch (e) {
      console.error('Error enrolling dataset:', e);
      return { success: false, message: 'Failed to enroll dataset' };
    }
  }

  async batchRecognize(datasetName: string, files: DatasetFile[], humanThreshold?: number, rekognitionThreshold?: number): Promise<BatchRecognizeResult> {
    try {
      const payload: any = { datasetName, files };
      if (humanThreshold != null) payload.humanThreshold = humanThreshold;
      if (rekognitionThreshold != null) payload.rekognitionThreshold = rekognitionThreshold;
      const response = await fetch(`${this.backendUrl}/api/batch-recognize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Batch recognize failed');
      return result;
    } catch (e) {
      console.error('Error batch recognizing:', e);
      return { success: false, message: 'Batch recognition failed' };
    }
  }

  async getEnrolledPeople(datasetName?: string): Promise<EnrolledPeopleResult> {
    try {
      const url = new URL(`${this.backendUrl}/api/enrolled-people`);
      if (datasetName) url.searchParams.set('datasetName', datasetName);
      const response = await fetch(url.toString(), {
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