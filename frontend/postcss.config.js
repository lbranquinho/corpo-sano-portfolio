import { fileURLToPath } from "node:url";

// Caminho absoluto: funciona mesmo quando o Vite é iniciado a partir de outra pasta.
const config = fileURLToPath(new URL("./tailwind.config.js", import.meta.url));

export default {
  plugins: {
    tailwindcss: { config },
    autoprefixer: {},
  },
};
