import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Image } from 'react-native';
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
            options={{
              title: '',
              headerTitleStyle: {
                fontFamily: 'Inter_600SemiBold',
                fontSize: 22,
              },
              headerShadowVisible: false,
              headerLeft: () => (
                <Image
                  source={require('./assets/logo.png')} // ✅ make sure path is correct
                  style={{
                    width: 110,
                    height: 110,
                    marginLeft: '20%',
                    marginTop: '40%',
                  }}
                  resizeMode="contain"
                />
              ),
            }}
          />
        </Stack.Navigator>
        <StatusBar style="auto" />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
