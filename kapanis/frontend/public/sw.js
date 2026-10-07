// Kapanış service worker: uygulama kabuğu, çevrimdışı ekranı ve uygulama bildirimleri.
// API cevapları asla önbelleğe alınmaz (veri hep canlı).
const CACHE = "kapanis-shell-v3";
const OFFLINE = "/offline.html";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", OFFLINE, "/manifest.json", "/icon-192.png"])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Sayfa gezinmesi: önce ağ; bağlantı yoksa "çevrimdışı" ekranı (veriler canlı olduğu için eski sayfa gösterilmez)
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE).then((hit) => hit || caches.match("/"))));
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/logos/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    })));
  }
});

// Uygulama bildirimi: sunucu (backend/push.py) şifreli gönderir, burada gösterilir
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { metin: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.baslik || "Kapanış", {
    body: d.metin || "", icon: "/icon-192.png", badge: "/icon-192.png", data: { url: d.url || "/app" },
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || "/app", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    const open = list.find((c) => new URL(c.url).origin === self.location.origin);
    if (open) return open.focus().then((c) => (c && "navigate" in c ? c.navigate(target) : null));
    return self.clients.openWindow(target);
  }));
});
