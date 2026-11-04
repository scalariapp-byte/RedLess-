// Le jeu était à la racine du site ; il est maintenant dans /jouer/ (avec son propre service worker).
// Ce fichier remplace l'ancien service worker de la racine : il efface l'ancienne copie hors ligne,
// se désinstalle, et renvoie les joueurs qui avaient installé Redlok vers le jeu.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: "window" });
    // Lien « Site de Redlok » du jeu (?site) : on recharge le site au lieu d'aller au jeu.
    clients.forEach((c) => c.navigate(new URL(c.url).searchParams.has("site") ? c.url : new URL("jouer/", self.registration.scope).href));
  })());
});
