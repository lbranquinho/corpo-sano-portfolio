/*
 * Corpo Sano — service worker do app instalável.
 * Regras de privacidade: NUNCA guarda respostas da API (/api/) — dados de clientes e saúde
 * não ficam no aparelho. Só guarda os arquivos do próprio site (JS/CSS/ícones) e uma página
 * "sem conexão".
 */
const VERSAO = "cs-v1";
const OFFLINE = "/offline.html";
const PRECACHE = [OFFLINE, "/favicon.svg", "/icons/apple-touch-icon.png", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSAO).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // dados: sempre da rede, nunca em cache

  // páginas: sempre a versão mais nova; sem internet, mostra o aviso
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }

  // arquivos versionados do build (nome muda a cada versão): cache primeiro
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((resp) => {
            if (resp.ok) {
              const copia = resp.clone();
              caches.open(VERSAO).then((c) => c.put(req, copia));
            }
            return resp;
          }),
      ),
    );
  }
});
