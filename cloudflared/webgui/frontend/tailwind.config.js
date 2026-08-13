/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cf: {
          orange: '#F6821F',
          dark: '#1B1B1B',
        },
      },
    },
  },
  plugins: [],
}
