import { useState, useEffect } from 'react';
import * as ImagePicker from 'expo-image-picker';

export const useImagePicker = () => {
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);

  useEffect(() => {
    requestPermissions();
  }, []);

  const requestPermissions = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    setHasPermission(status === 'granted');
  };

  const pickImage = async (): Promise<string | null> => {
    if (hasPermission === false) {
      return null;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [4, 3],
      quality: 1,
    });

    if (!result.canceled) {
      return result.assets[0].uri;
    }

    return null;
  };

  const takePhoto = async (): Promise<string | null> => {
    if (hasPermission === false) {
      return null;
    }

    const result = await ImagePicker.launchCameraAsync({
      allowsEditing: true,
      aspect: [4, 3],
      quality: 1,
    });

    if (!result.canceled) {
      return result.assets[0].uri;
    }

    return null;
  };

  return {
    hasPermission,
    pickImage,
    takePhoto,
    requestPermissions,
  };
};
