import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  Image,
  TextInput,
  ScrollView,
  Alert,
  ActivityIndicator,
  StyleSheet,
  Dimensions,
  Modal,
  FlatList,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import faceRecognitionService, { FaceMatch, EnrollmentResult, RecognitionResult } from '../services/faceRecognition';

const { width } = Dimensions.get('window');

interface EnrolledPerson {
  name: string;
  imageUri: string;
  enrolledAt: Date;
}

const FaceRecognitionScreen: React.FC = () => {
  const [enrollmentImage, setEnrollmentImage] = useState<string | null>(null);
  const [recognitionImage, setRecognitionImage] = useState<string | null>(null);
  const [personName, setPersonName] = useState<string>('');
  const [threshold, setThreshold] = useState<string>('80');
  const [isEnrolling, setIsEnrolling] = useState<boolean>(false);
  const [isRecognizing, setIsRecognizing] = useState<boolean>(false);
  const [recognitionResults, setRecognitionResults] = useState<FaceMatch[]>([]);
  const [enrollmentMessage, setEnrollmentMessage] = useState<string>('');
  const [enrolledPeople, setEnrolledPeople] = useState<EnrolledPerson[]>([]);
  const [showEnrolledModal, setShowEnrolledModal] = useState<boolean>(false);

  const pickImage = async (type: 'enrollment' | 'recognition') => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 1,
    });

    if (!result.canceled && result.assets[0]) {
      if (type === 'enrollment') {
        setEnrollmentImage(result.assets[0].uri);
      } else {
        setRecognitionImage(result.assets[0].uri);
        setRecognitionResults([]);
      }
    }
  };

  const enrollFace = async () => {
    if (!enrollmentImage || !personName.trim()) {
      Alert.alert('Error', 'Please select an image and enter a person name');
      return;
    }

    setIsEnrolling(true);
    setEnrollmentMessage('');

    try {
      // Using mock implementation for demo
      const result: EnrollmentResult = await faceRecognitionService.enrollFaceMock(
        enrollmentImage,
        personName.trim()
      );

      if (result.success) {
        setEnrollmentMessage(result.message || 'Face enrolled successfully!');
        // Add to enrolled people list
        const newPerson: EnrolledPerson = {
          name: personName.trim(),
          imageUri: enrollmentImage,
          enrolledAt: new Date(),
        };
        setEnrolledPeople(prev => [...prev, newPerson]);
        setPersonName('');
        setEnrollmentImage(null);
      } else {
        Alert.alert('Error', result.message || 'Failed to enroll face');
      }
    } catch (error) {
      Alert.alert('Error', 'An unexpected error occurred');
    } finally {
      setIsEnrolling(false);
    }
  };

  const recognizeFace = async () => {
    if (!recognitionImage) {
      Alert.alert('Error', 'Please select an image for recognition');
      return;
    }

    setIsRecognizing(true);
    setRecognitionResults([]);

    try {
      // Using mock implementation for demo
      const result: RecognitionResult = await faceRecognitionService.recognizeFaceMock(
        recognitionImage,
        parseFloat(threshold)
      );

      if (result.success) {
        setRecognitionResults(result.matches);
        if (result.matches.length === 0) {
          Alert.alert('No Matches', 'No matching faces found in the collection');
        }
      } else {
        Alert.alert('Error', result.message || 'Failed to recognize face');
      }
    } catch (error) {
      Alert.alert('Error', 'An unexpected error occurred');
    } finally {
      setIsRecognizing(false);
    }
  };

  const renderEnrolledPerson = ({ item }: { item: EnrolledPerson }) => (
    <View style={styles.enrolledPersonItem}>
      <Image
        source={{ uri: item.imageUri }}
        style={styles.enrolledPersonImage}
        resizeMode="cover"
      />
      <View style={styles.enrolledPersonInfo}>
        <Text style={styles.enrolledPersonName}>{item.name}</Text>
        <Text style={styles.enrolledPersonDate}>
          Enrolled: {item.enrolledAt.toLocaleDateString()}
        </Text>
      </View>
    </View>
  );

  return (
    <ScrollView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Fawkes vs Rekognition Demo</Text>

        {/* Header with View Enrolled Button */}
        <View style={styles.headerRow}>
          <TouchableOpacity
            onPress={() => setShowEnrolledModal(true)}
            style={styles.viewEnrolledButton}
          >
            <Text style={styles.viewEnrolledButtonText}>
              View Enrolled ({enrolledPeople.length})
            </Text>
          </TouchableOpacity>
        </View>

        <View style={styles.mainRow}>
          {/* Enrollment Side */}
          <View style={styles.column}>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Enroll Person</Text>
              
              <TouchableOpacity
                onPress={() => pickImage('enrollment')}
                style={styles.primaryButton}
              >
                <Text style={styles.buttonText}>
                  Select Image to Enroll
                </Text>
              </TouchableOpacity>

              {enrollmentImage && (
                <Image
                  source={{ uri: enrollmentImage }}
                  style={styles.imagePreview}
                  resizeMode="cover"
                />
              )}

              <TextInput
                style={styles.textInput}
                placeholder="Enter person's name"
                value={personName}
                onChangeText={setPersonName}
                placeholderTextColor="#9CA3AF"
              />

              <TouchableOpacity
                onPress={enrollFace}
                disabled={isEnrolling || !enrollmentImage || !personName.trim()}
                style={[
                  styles.button,
                  (isEnrolling || !enrollmentImage || !personName.trim()) 
                    ? styles.disabledButton 
                    : styles.successButton
                ]}
              >
                {isEnrolling ? (
                  <ActivityIndicator color="white" />
                ) : (
                  <Text style={styles.buttonText}>
                    Enroll Face
                  </Text>
                )}
              </TouchableOpacity>

              {enrollmentMessage && (
                <Text style={styles.successMessage}>
                  {enrollmentMessage}
                </Text>
              )}
            </View>
          </View>

          {/* Recognition Side */}
          <View style={styles.column}>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Recognize Face</Text>
              
              <TouchableOpacity
                onPress={() => pickImage('recognition')}
                style={styles.secondaryButton}
              >
                <Text style={styles.buttonText}>
                  Select Image to Test
                </Text>
              </TouchableOpacity>

              {recognitionImage && (
                <Image
                  source={{ uri: recognitionImage }}
                  style={styles.imagePreview}
                  resizeMode="cover"
                />
              )}

              <View style={styles.thresholdContainer}>
                <Text style={styles.thresholdLabel}>
                  Confidence Threshold: {threshold}%
                </Text>
                <TextInput
                  style={styles.textInput}
                  placeholder="80"
                  value={threshold}
                  onChangeText={setThreshold}
                  keyboardType="numeric"
                  placeholderTextColor="#9CA3AF"
                />
              </View>

              <TouchableOpacity
                onPress={recognizeFace}
                disabled={isRecognizing || !recognitionImage}
                style={[
                  styles.button,
                  (isRecognizing || !recognitionImage) 
                    ? styles.disabledButton 
                    : styles.dangerButton
                ]}
              >
                {isRecognizing ? (
                  <ActivityIndicator color="white" />
                ) : (
                  <Text style={styles.buttonText}>
                    Recognize Face
                  </Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>

        {/* Results Section */}
        {recognitionResults.length > 0 && (
          <View style={styles.resultsCard}>
            <Text style={styles.cardTitle}>Recognition Results</Text>
            
            {recognitionResults.map((match, index) => (
              <View key={index} style={styles.resultItem}>
                <Text style={styles.resultName}>
                  {match.externalImageId}
                </Text>
                <Text style={styles.resultDetail}>
                  Similarity: {match.similarity.toFixed(2)}%
                </Text>
                <Text style={styles.resultDetail}>
                  Confidence: {match.confidence.toFixed(2)}%
                </Text>
              </View>
            ))}
          </View>
        )}

        {/* Enrolled People Modal */}
        <Modal
          visible={showEnrolledModal}
          animationType="slide"
          transparent={true}
          onRequestClose={() => setShowEnrolledModal(false)}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>Enrolled People</Text>
                <TouchableOpacity
                  onPress={() => setShowEnrolledModal(false)}
                  style={styles.closeButton}
                >
                  <Text style={styles.closeButtonText}>×</Text>
                </TouchableOpacity>
              </View>
              
              {enrolledPeople.length === 0 ? (
                <Text style={styles.noEnrolledText}>No people enrolled yet</Text>
              ) : (
                <FlatList
                  data={enrolledPeople}
                  renderItem={renderEnrolledPerson}
                  keyExtractor={(item, index) => index.toString()}
                  style={styles.enrolledList}
                />
              )}
            </View>
          </View>
        </Modal>
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  content: {
    padding: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 16,
    color: '#1F2937',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginBottom: 16,
  },
  viewEnrolledButton: {
    backgroundColor: '#6B7280',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
  },
  viewEnrolledButtonText: {
    color: 'white',
    fontWeight: '500',
  },
  mainRow: {
    flexDirection: width > 768 ? 'row' : 'column',
    gap: 16,
  },
  column: {
    flex: 1,
    marginHorizontal: width > 768 ? 4 : 0,
  },
  card: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 3,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 16,
    color: '#374151',
  },
  button: {
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    marginBottom: 8,
  },
  primaryButton: {
    backgroundColor: '#3B82F6',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    marginBottom: 16,
  },
  secondaryButton: {
    backgroundColor: '#8B5CF6',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    marginBottom: 16,
  },
  successButton: {
    backgroundColor: '#10B981',
  },
  dangerButton: {
    backgroundColor: '#EF4444',
  },
  disabledButton: {
    backgroundColor: '#9CA3AF',
  },
  buttonText: {
    color: 'white',
    fontWeight: '500',
  },
  imagePreview: {
    width: '100%',
    height: width > 768 ? 200 : 180,
    borderRadius: 8,
    marginBottom: 16,
    maxHeight: 300,
  },
  textInput: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
    color: '#374151',
  },
  thresholdContainer: {
    marginBottom: 16,
  },
  thresholdLabel: {
    color: '#374151',
    marginBottom: 8,
  },
  successMessage: {
    marginTop: 8,
    color: '#10B981',
    textAlign: 'center',
  },
  resultsCard: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 3,
  },
  resultItem: {
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
    paddingBottom: 12,
    marginBottom: 12,
  },
  resultName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  resultDetail: {
    color: '#6B7280',
    marginTop: 2,
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 20,
    width: '90%',
    maxWidth: 500,
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  closeButton: {
    padding: 8,
  },
  closeButtonText: {
    fontSize: 24,
    color: '#6B7280',
  },
  noEnrolledText: {
    textAlign: 'center',
    color: '#6B7280',
    fontSize: 16,
    marginTop: 20,
  },
  enrolledList: {
    maxHeight: 400,
  },
  enrolledPersonItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  enrolledPersonImage: {
    width: 60,
    height: 60,
    borderRadius: 8,
    marginRight: 12,
  },
  enrolledPersonInfo: {
    flex: 1,
  },
  enrolledPersonName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  enrolledPersonDate: {
    fontSize: 14,
    color: '#6B7280',
    marginTop: 4,
  },
});

export default FaceRecognitionScreen;
