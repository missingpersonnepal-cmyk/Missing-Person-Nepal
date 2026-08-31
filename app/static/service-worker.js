const CACHE = 'missing-person-hub-v1';
const ASSETS = ['/', '/report', '/static/style.css', '/static/admin.css', '/static/default-person.svg'];
self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS))));
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => { const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put(event.request, copy)); return response; }).catch(() => caches.match('/'))));
});
