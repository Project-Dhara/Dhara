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
        sans: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        body: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        label: ['"DM Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        mono: ['"DM Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
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
      transitionTimingFunction: {
        dhara: 'cubic-bezier(0.22, 1, 0.36, 1)',
        'dhara-out': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      transitionDuration: {
        dhara: '420ms',
        'dhara-fast': '240ms',
        'dhara-slow': '560ms',
      },
      keyframes: {
        'toast-in': {
          from: { transform: 'translateY(-10px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
        'progress-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
        'fade-up': {
          from: { transform: 'translateY(10px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
        'soft-in': {
          from: { transform: 'scale(0.985)', opacity: '0' },
          to: { transform: 'scale(1)', opacity: '1' },
        },
      },
      animation: {
        'toast-in': 'toast-in 320ms cubic-bezier(0.16, 1, 0.3, 1)',
        'progress-pulse': 'progress-pulse 1.8s ease-in-out infinite',
        'fade-up': 'fade-up 480ms cubic-bezier(0.16, 1, 0.3, 1)',
        'tab-in': 'fade-up 420ms cubic-bezier(0.22, 1, 0.36, 1)',
        'soft-in': 'soft-in 420ms cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
}
