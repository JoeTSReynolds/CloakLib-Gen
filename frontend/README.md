# CloakLib Frontend

A React Native Expo application for the CloakLib image protection system.

## Features

- Image selection from gallery or camera
- Real-time image cloaking with adjustable protection levels
- Share and save processed images
- Modern, intuitive UI

## Prerequisites

- Node.js (v16 or higher)
- npm or yarn
- Expo CLI
- Android Studio (for Android development)
- Xcode (for iOS development, macOS only)

## Installation

1. Install dependencies:
```bash
npm install
```

2. Start the development server:
```bash
npm start
```

3. Use Expo Go app on your phone to scan the QR code, or run on simulator:
```bash
npm run android  # For Android
npm run ios      # For iOS
```

## Project Structure

```
frontend/
├── App.tsx                 # Main app component
├── src/
│   ├── screens/           # Screen components
│   │   ├── HomeScreen.tsx
│   │   ├── ImageCloakingScreen.tsx
│   │   └── ResultScreen.tsx
│   ├── components/        # Reusable components
│   │   ├── ProtectionLevelSelector.tsx
│   │   └── LoadingOverlay.tsx
│   ├── services/          # API services
│   │   └── api.ts
│   ├── utils/             # Utility functions
│   │   └── imageUtils.ts
│   └── types/             # TypeScript types
│       └── index.ts
├── assets/                # Images and static assets
└── package.json
```

## Configuration

Update the API base URL in `src/services/api.ts` to match your backend server:

```typescript
const API_BASE_URL = 'http://your-backend-url:port';
```

## Scripts

- `npm start` - Start the Expo development server
- `npm run android` - Run on Android device/emulator
- `npm run ios` - Run on iOS device/simulator
- `npm run web` - Run in web browser

## Dependencies

- React Native with Expo
- React Navigation for screen navigation
- Expo Image Picker for image selection
- Expo File System for file operations
- Expo Sharing for sharing functionality

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License.
