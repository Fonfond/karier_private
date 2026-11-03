/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: '#0B1014',
        surface1: '#121A21',
        surface2: '#182330',
        line: '#253242',
        ink: '#E6EDF3',
        ink2: '#9FB0C0',
        ink3: '#6B7A8A',
        accent: '#4C9AFF',
        warm: '#F5A524',
        ok: '#2FBF71',
        bad: '#F2545B',
        reserve: '#3D8BFD',
        ground: '#A56BFF',
      },
      fontFamily: {
        sans: ['-apple-system', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'JetBrains Mono', 'Consolas', 'monospace'],
      },
      borderRadius: {
        card: '12px',
        sheet: '16px',
      },
      boxShadow: {
        sheet: '0 -8px 30px rgba(0,0,0,0.45)',
      },
    },
  },
  plugins: [],
}
