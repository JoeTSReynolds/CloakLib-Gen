import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import HomeScreen from './src/screens/HomeScreen';
import ImageCloakingScreen from './src/screens/ImageCloakingScreen';
import ResultScreen from './src/screens/ResultScreen';
import FaceRecognitionScreen from './src/screens/FaceRecognitionScreen';

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <NavigationContainer>
        <Stack.Navigator initialRouteName="FaceRecognition">
          <Stack.Screen 
            name="FaceRecognition" 
            component={FaceRecognitionScreen} 
            options={{ title: 'Fawkes vs Rekognition Demo' }}
          />
          <Stack.Screen 
            name="Home" 
            component={HomeScreen} 
            options={{ title: 'CloakLib' }}
          />
          <Stack.Screen 
            name="ImageCloaking" 
            component={ImageCloakingScreen} 
            options={{ title: 'Cloak Image' }}
          />
          <Stack.Screen 
            name="Result" 
            component={ResultScreen} 
            options={{ title: 'Result' }}
          />
        </Stack.Navigator>
        <StatusBar style="auto" />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
