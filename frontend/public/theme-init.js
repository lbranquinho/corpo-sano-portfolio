// Aplica o tema (claro/escuro) antes da renderização para evitar "piscada".
// Arquivo externo para permitir Content-Security-Policy sem scripts inline.
try {
  var t = localStorage.getItem("cs-theme");
  if (t === "dark" || (!t && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("dark");
  }
} catch (e) {
  /* armazenamento indisponível */
}
