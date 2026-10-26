/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: 'rgb(var(--ink) / <alpha-value>)', 2: 'rgb(var(--ink-2) / <alpha-value>)', 3: 'rgb(var(--ink-3) / <alpha-value>)' },
        paper: 'rgb(var(--paper) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        sunk: 'rgb(var(--sunk) / <alpha-value>)',
        line: { DEFAULT: 'rgb(var(--line) / <alpha-value>)', strong: 'rgb(var(--line-strong) / <alpha-value>)' },
        text: { DEFAULT: 'rgb(var(--text) / <alpha-value>)', muted: 'rgb(var(--text-muted) / <alpha-value>)', faint: 'rgb(var(--text-faint) / <alpha-value>)', inverse: 'rgb(var(--text-inverse) / <alpha-value>)' },
        link: 'rgb(var(--link) / <alpha-value>)',
        ok: { DEFAULT: 'rgb(var(--ok) / <alpha-value>)', soft: 'rgb(var(--ok-soft) / <alpha-value>)' },
        warn: { DEFAULT: 'rgb(var(--warn) / <alpha-value>)', soft: 'rgb(var(--warn-soft) / <alpha-value>)' },
        bad: { DEFAULT: 'rgb(var(--bad) / <alpha-value>)', soft: 'rgb(var(--bad-soft) / <alpha-value>)' },
        sim: { DEFAULT: 'rgb(var(--sim) / <alpha-value>)', soft: 'rgb(var(--sim-soft) / <alpha-value>)' },
        idle: { DEFAULT: 'rgb(var(--idle) / <alpha-value>)', soft: 'rgb(var(--idle-soft) / <alpha-value>)' },
      },
      fontFamily: {
        sans: ['"Public Sans"', 'system-ui', 'sans-serif'],
        serif: ['"Source Serif 4"', 'Georgia', 'serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: { sm: '3px', DEFAULT: '5px', md: '6px', lg: '8px' },
      boxShadow: {
        lift: '0 1px 0 rgba(12,27,51,.04), 0 6px 18px -10px rgba(12,27,51,.35)',
        pop: '0 12px 40px -12px rgba(12,27,51,.45)',
      },
    },
  },
  plugins: [],
}
