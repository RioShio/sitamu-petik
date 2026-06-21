/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js"
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "primary": "#0047A0", // Biru Tua
        "secondary": "#00B5CC", // Cyan/Teal
        "tertiary": "#FDD043", // Kuning
        "surface": "#F8FAFC",
        "surface-container": "#E2E8F0",
        "surface-container-low": "#F1F5F9",
        "surface-container-highest": "#CBD5E1",
        "surface-container-lowest": "#FFFFFF",
        "on-surface": "#0F172A",
        "on-surface-variant": "#475569",
        "outline-variant": "#94A3B8",
        "error": "#DC2626",
        "on-error": "#FFFFFF",
        "primary-container": "#DBEAFE",
        "on-primary-container": "#1E3A8A"
      }
    }
  },
  plugins: [],
}