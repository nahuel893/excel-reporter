import type { Config } from 'tailwindcss'

export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        paper: '#FAF7F0',
        'paper-rule': '#E5DECF',
        'paper-hover': '#F0EBE0',
        ink: '#1A1714',
        'ink-soft': '#5C544A',
        'header-navy': '#1F4E78',
        'band-green': '#548235',
        'band-purple': '#7030A0',
        'band-red': '#FF0000',
        'sem-red': '#FF0000',
        'sem-yellow': '#FFFF00',
        'sem-green': '#00B050',
        mmaa: '#C00000',
        ma: '#808000',
        objetivo: '#4472C4',
        amber: {
          50: '#FFFBEB',
          100: '#FEF3C7',
          200: '#FDE68A',
          600: '#D97706',
          700: '#B45309',
          800: '#92400E',
        },
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
        body: ['Fraunces', 'Georgia', 'serif'],
      },
      backgroundImage: {
        'paper-grain': "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E\")",
      },
      animation: {
        'fade-up': 'fadeUp 0.4s ease-out both',
      },
      keyframes: {
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
