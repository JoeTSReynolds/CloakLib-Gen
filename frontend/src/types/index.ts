export interface NavigationParams {
  Home: undefined;
  ImageCloaking: undefined;
  Result: {
    originalImage: string;
    processedImage: string;
  };
}

export type ProtectionLevel = 'low' | 'mid' | 'high';

export interface ImageProcessingOptions {
  protectionLevel: ProtectionLevel;
  preserveQuality: boolean;
}
