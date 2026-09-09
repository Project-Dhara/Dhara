/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Official brand schema + deep surface green for dark panels / code.
        // Primary Deep Teal
        teal: '#176B6B',
        'teal-dark': '#125757',
        // Deep surface (API blocks, auth panel, dense chrome)
        'teal-deep': '#12403E',
        // Aliases for intent naming — primary actions / nav use forest (= teal)
        forest: '#176B6B',
        'forest-light': '#1F8C8C',
        'forest-dark': '#12403E',
        'forest-tint': '#E7F0DF',
        // Background Warm Ivory
        cream: '#FFF7EA',
        'outer-bg': '#FFF7EA',
        // Accent 2 Data Yellow
        yellow: '#F2C230',
        // Secondary Leaf Green — success / done
        green: '#73A942',
        // Accent 1 Warm Coral
        coral: '#D95B68',
        // Soft Green BG
        sage: '#E7F0DF',
        // Dark / Text Charcoal
        ink: '#303337',
        'ink-soft': '#6E7378',
        line: '#E8DFD0',
        surface: '#ffffff',
      },
      fontFamily: {
        display: ['Space Grotesk', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        body: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '16px',
      },
      boxShadow: {
        // Quieter elevation for a light, minimal feel
        dhara: '0 12px 32px rgba(48, 51, 55, 0.08)',
        card: '0 1px 2px rgba(23, 107, 107, 0.04), 0 8px 20px rgba(23, 107, 107, 0.05)',
        hover: '0 4px 14px rgba(23, 107, 107, 0.08), 0 12px 28px rgba(23, 107, 107, 0.08)',
        'focus-ring': '0 0 0 3px rgba(23, 107, 107, 0.16)',
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
        'fade-up': {
          from: { transform: 'translateY(6px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        'toast-in': 'toast-in 200ms ease-out',
        'progress-pulse': 'progress-pulse 1.6s ease-in-out infinite',
        'fade-up': 'fade-up 320ms cubic-bezier(0.16, 1, 0.3, 1)',
        'tab-in': 'fade-up 280ms cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
}
