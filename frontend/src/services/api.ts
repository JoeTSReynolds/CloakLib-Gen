// API service for communicating with CloakLib backend
const API_BASE_URL = 'http://localhost:8000'; // Adjust based on your backend

export interface CloakingRequest {
  image: string; // Base64 encoded image
  protection_level: 'low' | 'mid' | 'high';
}

export interface CloakingResponse {
  success: boolean;
  cloaked_image: string; // Base64 encoded cloaked image
  message?: string;
}

export const cloakImage = async (request: CloakingRequest): Promise<CloakingResponse> => {
  try {
    const response = await fetch(`${API_BASE_URL}/cloak`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error cloaking image:', error);
    throw error;
  }
};

export const healthCheck = async (): Promise<boolean> => {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    return response.ok;
  } catch (error) {
    console.error('Health check failed:', error);
    return false;
  }
};
