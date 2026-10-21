/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "PingFang SC", "Microsoft YaHei", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "Consolas", "monospace"],
      },
      colors: {
        ink: {
          50: "#f9fafb",
          100: "#f3f4f6",
          200: "#e5e7eb",
          300: "#d1d5db",
          400: "#9ca3af",
          500: "#6b7280",
          600: "#4b5563",
          700: "#374151",
          800: "#1f2937",
          900: "#111827",
          950: "#0a0a0a",
        },
        accent: {
          50: "#eef6ff",
          100: "#d9ebff",
          200: "#b9d6ff",
          300: "#8ab9ff",
          400: "#5b93ff",
          500: "#2f6ff5",
          600: "#1d4fd8",
          700: "#1a3fa8",
          800: "#1a3a85",
          900: "#1a3572",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(0,0,0,.04), 0 1px 3px 0 rgba(0,0,0,.06)",
        pop: "0 10px 30px -10px rgba(17,24,39,.20)",
      },
    },
  },
};
