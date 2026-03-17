/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  theme: {
    extend: {
      fontFamily: { 'inter': ['Inter', 'sans-serif'] },
      colors: {
        dark: '#08080f',
        gold: { 400: '#c8aa6e', 500: '#b8963e', 600: '#a8862e' },
        glass: 'rgba(255,255,255,0.06)',
      }
    }
  },
  plugins: [],
}
