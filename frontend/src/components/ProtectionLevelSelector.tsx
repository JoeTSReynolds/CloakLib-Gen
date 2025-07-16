import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';

interface ProtectionLevelSelectorProps {
  selectedLevel: 'low' | 'mid' | 'high';
  onLevelChange: (level: 'low' | 'mid' | 'high') => void;
}

const ProtectionLevelSelector: React.FC<ProtectionLevelSelectorProps> = ({
  selectedLevel,
  onLevelChange,
}) => {
  const levels = [
    { key: 'low', label: 'Low', description: 'Basic protection' },
    { key: 'mid', label: 'Medium', description: 'Balanced protection' },
    { key: 'high', label: 'High', description: 'Maximum protection' },
  ] as const;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Protection Level</Text>
      <View style={styles.levelContainer}>
        {levels.map((level) => (
          <TouchableOpacity
            key={level.key}
            style={[
              styles.levelButton,
              selectedLevel === level.key && styles.selectedLevel,
            ]}
            onPress={() => onLevelChange(level.key)}
          >
            <Text
              style={[
                styles.levelLabel,
                selectedLevel === level.key && styles.selectedLevelLabel,
              ]}
            >
              {level.label}
            </Text>
            <Text
              style={[
                styles.levelDescription,
                selectedLevel === level.key && styles.selectedLevelDescription,
              ]}
            >
              {level.description}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    marginVertical: 20,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#2c3e50',
    marginBottom: 15,
    textAlign: 'center',
  },
  levelContainer: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  levelButton: {
    flex: 1,
    backgroundColor: '#ecf0f1',
    padding: 15,
    marginHorizontal: 5,
    borderRadius: 10,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  selectedLevel: {
    backgroundColor: '#3498db',
    borderColor: '#2980b9',
  },
  levelLabel: {
    fontSize: 16,
    fontWeight: '600',
    color: '#34495e',
    marginBottom: 5,
  },
  selectedLevelLabel: {
    color: 'white',
  },
  levelDescription: {
    fontSize: 12,
    color: '#7f8c8d',
    textAlign: 'center',
  },
  selectedLevelDescription: {
    color: 'rgba(255, 255, 255, 0.9)',
  },
});

export default ProtectionLevelSelector;
