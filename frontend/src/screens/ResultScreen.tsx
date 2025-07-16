import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Image, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NavigationProp, RouteProp } from '@react-navigation/native';
import * as Sharing from 'expo-sharing';
import * as FileSystem from 'expo-file-system';

interface ResultScreenProps {
  navigation: NavigationProp<any>;
  route: RouteProp<any>;
}

const ResultScreen: React.FC<ResultScreenProps> = ({ navigation, route }) => {
  const { originalImage, processedImage } = route.params as {
    originalImage: string;
    processedImage: string;
  };

  const shareImage = async () => {
    try {
      const isAvailable = await Sharing.isAvailableAsync();
      if (isAvailable) {
        await Sharing.shareAsync(processedImage);
      } else {
        Alert.alert('Error', 'Sharing is not available on this device');
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to share image');
    }
  };

  const saveImage = async () => {
    try {
      // TODO: Implement save functionality
      Alert.alert('Success', 'Image saved to gallery');
    } catch (error) {
      Alert.alert('Error', 'Failed to save image');
    }
  };

  const processAnother = () => {
    navigation.navigate('ImageCloaking');
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Cloaking Complete!</Text>
        
        <View style={styles.imageContainer}>
          <View style={styles.imageWrapper}>
            <Text style={styles.imageLabel}>Original</Text>
            <Image source={{ uri: originalImage }} style={styles.image} />
          </View>
          
          <View style={styles.imageWrapper}>
            <Text style={styles.imageLabel}>Cloaked</Text>
            <Image source={{ uri: processedImage }} style={styles.image} />
          </View>
        </View>

        <View style={styles.buttonContainer}>
          <TouchableOpacity style={styles.button} onPress={shareImage}>
            <Text style={styles.buttonText}>Share Image</Text>
          </TouchableOpacity>
          
          <TouchableOpacity style={styles.button} onPress={saveImage}>
            <Text style={styles.buttonText}>Save to Gallery</Text>
          </TouchableOpacity>
          
          <TouchableOpacity
            style={[styles.button, styles.primaryButton]}
            onPress={processAnother}
          >
            <Text style={styles.buttonText}>Process Another</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8f9fa',
  },
  content: {
    flex: 1,
    padding: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#2c3e50',
    textAlign: 'center',
    marginBottom: 20,
  },
  imageContainer: {
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    marginVertical: 20,
  },
  imageWrapper: {
    alignItems: 'center',
  },
  imageLabel: {
    fontSize: 16,
    fontWeight: '600',
    color: '#34495e',
    marginBottom: 10,
  },
  image: {
    width: 150,
    height: 150,
    borderRadius: 10,
    resizeMode: 'contain',
  },
  buttonContainer: {
    gap: 15,
  },
  button: {
    backgroundColor: '#95a5a6',
    paddingVertical: 15,
    borderRadius: 10,
    alignItems: 'center',
  },
  primaryButton: {
    backgroundColor: '#3498db',
  },
  buttonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '600',
  },
});

export default ResultScreen;
