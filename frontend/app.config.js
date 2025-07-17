export default {
  expo: {
    name: "Fawkes vs Rekognition Demo",
    slug: "fawkes-rekognition-demo",
    version: "1.0.0",
    orientation: "landscape",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    splash: {
      image: "./assets/splash.png",
      resizeMode: "contain",
      backgroundColor: "#ffffff"
    },
    assetBundlePatterns: [
      "**/*"
    ],
    web: {
      bundler: "metro",
      favicon: "./assets/favicon.png"
    },
    extra: {
      awsBucketName: process.env.EXPO_PUBLIC_AWS_BUCKET_NAME,
      awsProfileName: process.env.EXPO_PUBLIC_AWS_PROFILE_NAME,
      awsRegion: process.env.EXPO_PUBLIC_AWS_REGION,
      collectionId: process.env.EXPO_PUBLIC_COLLECTION_ID
    }
  }
};
