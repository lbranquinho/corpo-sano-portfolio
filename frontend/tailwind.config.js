import { fileURLToPath } from "node:url";
import colors from "tailwindcss/colors";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

/** @type {import('tailwindcss').Config} */
export default {
  content: [here("./index.html"), here("./src") + "/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          900: "#1E3A8A",
        },
        aqua: "#38BDF8",
        lavender: "#EDE9FE",
        // violeta da marca = violet-500; mantém a escala completa (violet-200, violet-700...)
        violet: { ...colors.violet, DEFAULT: "#8B5CF6" },
        // rosa da marca (decorativo). "rose" fica com o vermelho padrão, usado para perigo e erro.
        blossom: { 100: "#FCE7F3", 200: "#FBCFE8", 500: "#EC4899", 700: "#BE185D" },
        slateblue: "#64748B",
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        script: ['"Dancing Script"', "cursive"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(30, 58, 138, 0.06)",
      },
      borderRadius: { xl2: "1.125rem" },
    },
  },
  plugins: [],
};
