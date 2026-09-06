/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        teal: '#176B6B',
        'teal-dark': '#125757',
        'teal-deep': '#10403F',
        cream: '#FFF7EA',
        'outer-bg': '#F0E7D6',
        yellow: '#F2C230',
        green: '#73A942',
        coral: '#D95B68',
        sage: '#E7F0DF',
        ink: '#303337',
        'ink-soft': '#6E7378',
        line: '#e6dcc8',
        surface: '#ffffff',
      },
      fontFamily: {
        display: ['Bespoke Stencil', 'Inter', 'sans-serif'],
        body: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        dhara: '0 16px 36px rgba(48, 51, 55, 0.12)',
      },
      keyframes: {
        'toast-in': {
          from: { transform: 'translateY(-8px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
        'progress-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
      },
      animation: {
        'toast-in': 'toast-in 200ms ease-out',
        'progress-pulse': 'progress-pulse 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
