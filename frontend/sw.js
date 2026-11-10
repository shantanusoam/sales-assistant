const CACHE_NAME = 'sales-copilot-shell-v1';
const SHELL_ASSETS = [
  '/',
  '/login',
  '/signup',
  '/history',
  '/settings',
  '/favicon.svg',
  '/manifest.webmanifest',
  '/assets/style.css',
  '/assets/api.js',
  '/assets/app.js',
  '/assets/history.js',
  '/assets/settings.js',
  '/assets/login.js',
  '/assets/signup.js',
  '/assets/pcm-worklet.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;

  // Network-first so code updates arrive immediately, falling back to cache when offline
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.status === 200 && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone)).catch(() => {});
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
