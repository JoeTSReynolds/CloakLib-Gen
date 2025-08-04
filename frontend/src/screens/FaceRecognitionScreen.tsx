import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  Image,
  TextInput,
  ScrollView,
  Alert,
  ActivityIndicator,
  Dimensions,
  Modal,
  FlatList,
  StyleSheet,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import faceRecognitionService, { FaceMatch, EnrollmentResult, RecognitionResult, EnrolledPerson } from '../services/faceRecognition';
import {
  useFonts,
  Inter_400Regular,
  Inter_600SemiBold,
  Inter_500Medium,
} from '@expo-google-fonts/inter';

const { width } = Dimensions.get('window');

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

const [fontsLoaded] = useFonts({
  Inter_400Regular,
  Inter_600SemiBold,
});

 useEffect(() => {
    loadEnrolledPeople();
  }, []);

  const loadEnrolledPeople = async () => {
    try {
      const result = await faceRecognitionService.getEnrolledPeople();
      if (result.success) {
        // Convert the enrolled people to match the local interface
        const localEnrolledPeople: EnrolledPerson[] = result.enrolledPeople.map(person => ({
          name: person.name,
          imageUri: '', // We don't have image URIs from the backend, so use empty string
          enrolledAt: person.enrolledAt ? new Date(person.enrolledAt) : new Date(),
        }));
        setEnrolledPeople(localEnrolledPeople);
      }
    } catch (error) {
      console.error('Error loading enrolled people:', error);
    }
  };


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
    Alert.alert('Enrolling face', `Image: ${enrollmentImage}, Name: ${personName}`);

    if (!enrollmentImage || !personName.trim()) {
      Alert.alert('Error', 'Please select an image and enter a person name');
      return;
    }

    setIsEnrolling(true);
    setEnrollmentMessage('');

    try {
      // Use real AWS backend implementation
      const result: EnrollmentResult = await faceRecognitionService.enrollFace(
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
        
        await loadEnrolledPeople();
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
      // Use real AWS backend implementation
      const result: RecognitionResult = await faceRecognitionService.recognizeFace(
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
    <View style={styles.enrolledPersonContainer}>
      {item.imageUri ? (
        <Image
          source={{ uri: item.imageUri }}
          style={styles.enrolledPersonImage}
          resizeMode="cover"
        />
      ) : (
        <View style={[styles.enrolledPersonImage, styles.placeholderImage]}>
          <Text style={styles.placeholderText}>
            {item.name.charAt(0).toUpperCase()}
          </Text>
        </View>
      )}
      <View style={styles.enrolledPersonInfo}>
        <Text style={styles.enrolledPersonName}>{item.name}</Text>
        {item.enrolledAt != null && (
          <Text style={styles.enrolledPersonDate}>
        Enrolled: {item.enrolledAt.toLocaleDateString()}
          </Text>
        )}
      </View>
    </View>
  );

  return (
    <ScrollView style={styles.container}>
      <View style={styles.content}>
        <View style={styles.logocontainer}>
        <Image
          source={require('./logoimg.png')}
          style={styles.logo} 
        />
        </View>
        {/* Header with View Enrolled Button */}
        <View style={styles.textcontainer}>
          <Text style={styles.sectionHeading}>
              What do we do?
          </Text>
          <Text style={styles.textbody}>
            We build cutting-edge technology to detect image cloaking - a subtle yet powerful method used to bypass facial recognition systems and a rising threat in the world of digital identity.{"\n"} {"\n"}
            
            Image cloaking is a technique that subtly alters visual artefacts at the pixel level to deceive facial recognition systems, while appearing completely normal to the human eye. These tools are becoming increasingly accessible, enabling individuals and malicious actors to manipulate their digital identities or hide from automated detection. 
            {"\n"}{"\n"}Our software exposes these hidden manipulations.{"\n"}{"\n"}
            
            Using advanced detection algorithms, we can analyse the underlying structure, noise patterns, and feature-space shifts in images. Our technology can distinguish between genuine visual artefacts and those that have been adversarially modified. It works seamlessly across formats, lighting conditions, and even on low-resolution or compressed images. Whether used in security, authentication, social media moderation, or forensic analysis. Our detection engine restores trust in visual data. {"\n"}{"\n"}
          </Text>
        </View>
        <View style={styles.imgcontainer}>
          <View style={styles.columnleft}>
            <Image source={require('./person1.jpeg')} style={styles.cloakedimage} />
          </View>
          <View style={styles.columnright}>
            <Image source={require('./person1_cloaked.png')} style={styles.cloakedimage} />
          </View>
</View>
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

        <View style={width > 768 ? styles.desktopLayout : styles.mobileLayout}>
          {/* Enrollment Side */}
          <View style={styles.sectionContainer}>
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Enroll Person</Text>
              
              <TouchableOpacity
                onPress={() => {
                  console.log("Picking enrollment image");
                  pickImage('enrollment');
                }}
                style={styles.selectImageButton}
              >
                <Text style={styles.selectImageButtonText}>
                  Select Image to Enroll
                </Text>
              </TouchableOpacity>

              {enrollmentImage && (
                <Image
                  source={{ uri: enrollmentImage }}
                  style={[
                    styles.selectedImage,
                    { height: width > 768 ? 200 : 180 }
                  ]}
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
                onPress={() => {
                  console.log('Enrolling face with image:', enrollmentImage, 'and name:', personName);
                  enrollFace();
                }}
                disabled={isEnrolling || !enrollmentImage || !personName.trim()}
                style={[
                  styles.actionButton,
                  styles.enrollButton,
                  (isEnrolling || !enrollmentImage || !personName.trim()) && styles.disabledButton
                ]}
              >
                {isEnrolling ? (
                  <ActivityIndicator color="white" />
                ) : (
                  <Text style={styles.actionButtonText}>
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
          <View style={styles.sectionContainer}>
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Recognize Face</Text>
              
              <TouchableOpacity
                onPress={() => pickImage('recognition')}
                style={styles.recognizeImageButton}
              >
                <Text style={styles.selectImageButtonText}>
                  Select Image to Test
                </Text>
              </TouchableOpacity>

              {recognitionImage && (
                <Image
                  source={{ uri: recognitionImage }}
                  style={[
                    styles.selectedImage,
                    { height: width > 768 ? 200 : 180 }
                  ]}
                  resizeMode="cover"
                />
              )}

              <View style={styles.thresholdContainer}>
                <Text style={styles.thresholdLabel}>
                  Similarity Threshold: {threshold}%
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
                  styles.actionButton,
                  styles.recognizeButton,
                  (isRecognizing || !recognitionImage) && styles.disabledButton
                ]}
              >
                {isRecognizing ? (
                  <ActivityIndicator color="white" />
                ) : (
                  <Text style={styles.actionButtonText}>
                    Recognize Face
                  </Text>
                )}
              </TouchableOpacity>

              {/* Recognition Results */}
              {recognitionResults.length > 0 && (
                <View style={styles.resultsContainer}>
                  <Text style={styles.resultsTitle}>
                    Recognition Results
                  </Text>
                  {recognitionResults.map((match, index) => (
                    <View
                      key={index}
                      style={[
                        styles.resultItem,
                        index < recognitionResults.length - 1 && styles.resultItemBorder
                      ]}
                    >
                      <Text style={styles.resultName}>
                        {match.externalImageId}
                      </Text>
                      <Text style={styles.resultDetail}>
                        Similarity: {match.similarity.toFixed(1)}%
                      </Text>
                      <Text style={styles.resultDetail}>
                        Confidence: {match.confidence.toFixed(1)}%
                      </Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>
        </View>

        {/* Modal for Enrolled People */}
        <Modal
          visible={showEnrolledModal}
          transparent={true}
          animationType="slide"
          onRequestClose={() => setShowEnrolledModal(false)}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>
                  Enrolled People
                </Text>
                <TouchableOpacity
                  onPress={() => setShowEnrolledModal(false)}
                  style={styles.closeButton}
                >
                  <Text style={styles.closeButtonText}>×</Text>
                </TouchableOpacity>
              </View>
              
              {enrolledPeople.length === 0 ? (
                <Text style={styles.emptyMessage}>
                  No people enrolled yet
                </Text>
              ) : (
                <FlatList
                  data={enrolledPeople}
                  renderItem={renderEnrolledPerson}
                  keyExtractor={(item: EnrolledPerson, index: number) => index.toString()}
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

export default FaceRecognitionScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    fontFamily: 'Inter_400Regular',
  },
  content: {
    padding: 16,
  },
  logocontainer: {
    alignItems: 'center',
    marginTop: 10,
    marginBottom: 10,
    paddingHorizontal: 20,
    width: '100%',
  },
  logo: {
    resizeMode: 'contain',
    marginTop: 150,
    marginBottom: 150,
    width: '60%',
    height: undefined,
  },
  title: {
    fontSize: 24,
    fontFamily: 'Inter_600SemiBold',
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 20,
    color: '#1F2937',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
    fontFamily: 'Inter_400Regular',
  },
  viewEnrolledButton: {
    backgroundColor: '#6B7280',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    fontFamily: 'Inter_400Regular',
  },
  viewEnrolledButtonText: {
    color: 'white',
    fontWeight: '500',
    fontFamily: 'Inter_400Regular',
  },
  desktopLayout: {
    flexDirection: 'row',
    gap: 16,
  },
  mobileLayout: {
    flexDirection: 'column',
    gap: 16,
  },
  sectionContainer: {
    flex: 1,
    marginHorizontal: 4,
  },
  card: {
    backgroundColor: '#fffff',
    borderRadius: 8,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 16,
    color: '#374151',
    fontFamily: 'Inter_400Regular',
  },
  textcontainer: {
    marginTop: 10,
    marginBottom: 10,
    padding: 25,
    width: '100%',
  },
  sectionHeading: {
    fontSize: 40,
    marginBottom: 16,
    color: '#000000',
    fontWeight: '600',
  },
  textbody: {
    fontSize: 20,
    fontFamily: 'Inter_400Regular',
    color: '#404040',
    fontWeight: '400',
  },
  imgcontainer: {
    flexDirection: 'row', // horizontal layout
    justifyContent: 'space-between', // space between the 2 columns
    padding: 10,
  },
  columnleft: {
    flex: 1,
    alignItems: 'center',
  },
  columnright: {
    flex: 1,
    alignItems: 'center',
  },
  cloakedimage: {
    width: '90%', // relative width inside column
    aspectRatio: 1, // keeps it square
    resizeMode: 'cover',
    borderRadius: 10,
  },
  selectImageButton: {
    backgroundColor: '#2563EB',
    padding: 12,
    borderRadius: 6,
    alignItems: 'center',
    marginBottom: 16,
  },
  recognizeImageButton: {
    backgroundColor: '#7C3AED',
    padding: 12,
    borderRadius: 6,
    alignItems: 'center',
    marginBottom: 16,
  },
  selectImageButtonText: {
    color: 'white',
    fontWeight: '500',
  },
  selectedImage: {
    width: '100%',
    borderRadius: 6,
    marginBottom: 16,
    maxHeight: 300,
  },
  textInput: {
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 6,
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
  actionButton: {
    padding: 12,
    borderRadius: 6,
    alignItems: 'center',
    marginBottom: 16,
  },
  enrollButton: {
    backgroundColor: '#059669',
  },
  recognizeButton: {
    backgroundColor: '#D97706',
  },
  disabledButton: {
    backgroundColor: '#9CA3AF',
  },
  actionButtonText: {
    color: 'white',
    fontWeight: '500',
  },
  successMessage: {
    marginTop: 8,
    color: '#059669',
    textAlign: 'center',
  },
  resultsContainer: {
    backgroundColor: 'white',
    borderRadius: 8,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
    marginTop: 16,
  },
  resultsTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 16,
    color: '#1F2937',
  },
  resultItem: {
    paddingBottom: 12,
    marginBottom: 12,
  },
  resultItemBorder: {
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
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
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 8,
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
  emptyMessage: {
    textAlign: 'center',
    color: '#6B7280',
    fontSize: 16,
    marginTop: 20,
  },
  enrolledList: {
    maxHeight: 400,
  },
  enrolledPersonContainer: {
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
  placeholderImage: {
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
  },
  placeholderText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#6B7280',
  },
});
