// Same palette as the Pi HMI's StartrekGraphical theme
// (carpediem/hmi_qt/theme.py), so the phone and the boat's display read as
// one product.
export const colors = {
  bg: '#030509',
  bgHi: '#090E16',
  panel: '#090F18',
  panelHi: '#0F1824',
  border: '#2D5569',
  accent: '#FF9900',
  accentDim: '#78501E',
  secondary: '#66CCFF',
  tertiary: '#CC99FF',
  text: '#E2F6FF',
  textDim: '#7896A5',
  ok: '#33FF66',
  warn: '#FFAA28',
  danger: '#FF3C3C',
  neutral: '#828C96',
};

// Loaded in App.tsx via @expo-google-fonts.
export const fonts = {
  display: 'Orbitron_700Bold',
  displayBlack: 'Orbitron_900Black',
  displayMedium: 'Orbitron_500Medium',
  label: 'Rajdhani_600SemiBold',
  labelBold: 'Rajdhani_700Bold',
  body: 'Rajdhani_500Medium',
};

export const radius = { card: 18, chip: 12 };
