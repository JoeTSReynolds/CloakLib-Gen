// This file contains app-wide constants and configuration

export const APP_CONFIG = {
  name: 'CloakLib',
  version: '1.0.0',
  author: 'Your Name',
  description: 'Advanced image protection using cloaking technology',
};

export const API_CONFIG = {
  baseURL: 'http://localhost:8000',
  timeout: 30000,
  endpoints: {
    cloak: '/cloak',
    health: '/health',
  },
};

export const PROTECTION_LEVELS = {
  low: {
    label: 'Low',
    description: 'Basic protection with minimal quality loss',
    value: 'low',
  },
  mid: {
    label: 'Medium',
    description: 'Balanced protection and quality',
    value: 'mid',
  },
  high: {
    label: 'High',
    description: 'Maximum protection with some quality trade-off',
    value: 'high',
  },
} as const;

export const COLORS = {
  primary: '#3498db',
  secondary: '#2ecc71',
  accent: '#e74c3c',
  background: '#f8f9fa',
  text: '#2c3e50',
  textSecondary: '#7f8c8d',
  border: '#bdc3c7',
  success: '#27ae60',
  warning: '#f39c12',
  error: '#e74c3c',
};

export const FONTS = {
  regular: 'System',
  medium: 'System',
  bold: 'System',
  light: 'System',
};

export const SIZES = {
  padding: 20,
  margin: 15,
  borderRadius: 10,
  headerHeight: 60,
  buttonHeight: 50,
};
