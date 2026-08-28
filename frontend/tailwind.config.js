/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: 'rgb(var(--c-canvas) / <alpha-value>)',
        surface: 'rgb(var(--c-surface) / <alpha-value>)',
        sunken: 'rgb(var(--c-sunken) / <alpha-value>)',
        line: 'rgb(var(--c-line) / <alpha-value>)',
        strong: 'rgb(var(--c-line-strong) / <alpha-value>)',
        ink: 'rgb(var(--c-ink) / <alpha-value>)',
        muted: 'rgb(var(--c-muted) / <alpha-value>)',
        faint: 'rgb(var(--c-faint) / <alpha-value>)',
        accent: {
          DEFAULT: 'rgb(var(--c-accent) / <alpha-value>)',
          soft: 'rgb(var(--c-accent-soft) / <alpha-value>)',
          line: 'rgb(var(--c-accent-line) / <alpha-value>)',
        },
        pass: {
          DEFAULT: 'rgb(var(--c-pass) / <alpha-value>)',
          soft: 'rgb(var(--c-pass-soft) / <alpha-value>)',
        },
        warn: {
          DEFAULT: 'rgb(var(--c-warn) / <alpha-value>)',
          soft: 'rgb(var(--c-warn-soft) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'rgb(var(--c-danger) / <alpha-value>)',
          soft: 'rgb(var(--c-danger-soft) / <alpha-value>)',
        },
        info: {
          DEFAULT: 'rgb(var(--c-info) / <alpha-value>)',
          soft: 'rgb(var(--c-info-soft) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['Newsreader', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--c-shadow) / 0.05), 0 1px 3px rgb(var(--c-shadow) / 0.04)',
        lift: '0 2px 4px rgb(var(--c-shadow) / 0.05), 0 8px 24px -8px rgb(var(--c-shadow) / 0.12)',
        pop: '0 12px 40px -12px rgb(var(--c-shadow) / 0.28)',
      },
      keyframes: {
        'fade-up': { '0%': { opacity: '0', transform: 'translateY(8px)' }, '100%': { opacity: '1', transform: 'none' } },
        'fade-in': { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        'slide-in': { '0%': { opacity: '0', transform: 'translateX(-6px)' }, '100%': { opacity: '1', transform: 'none' } },
        'sheen': { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
      },
      animation: {
        'fade-up': 'fade-up .32s cubic-bezier(.22,.8,.3,1) both',
        'fade-in': 'fade-in .24s ease-out both',
        'slide-in': 'slide-in .22s ease-out both',
        'sheen': 'sheen 1.6s linear infinite',
      },
    },
  },
  plugins: [],
}
