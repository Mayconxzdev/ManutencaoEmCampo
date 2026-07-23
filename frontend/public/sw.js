const CURRENT_VERSION = '1.0.0-demo';
const CACHE_NAME = `mec-cache-${CURRENT_VERSION}`;
const RUNTIME_CACHE = `mec-runtime-${CURRENT_VERSION}`;
const API_CACHE = `mec-api-readonly-${CURRENT_VERSION}`;
const SHELL = ['/', '/index.html', '/mec-maintenance-icon.svg', '/icon-192.png', '/icon-512.png', '/manifest.webmanifest'];
const API_PREFIXES = [
  '/ping', '/health', '/v2/system/capabilities', '/v2/system/diagnostics', '/v2/system/readiness', '/v2/system/integrity', '/v2/system/compatibility', '/v2/search/global', '/v2/search/status',
  '/v2/offline/status', '/v2/decisions/queue', '/v2/document-review/summary', '/v2/document-review/items', '/v2/document-review/ocr/jobs', '/v2/permissions/matrix', '/v2/permissions/me', '/v2/observability/requests', '/v2/file-limits', '/sectors', '/operators', '/assets', '/checklists', '/orders', '/issues',
  '/reports', '/resolve-token', '/v2/cmp'
];
const STATIC_EXTENSIONS = ['.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.woff2'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys
        .filter(key => key.startsWith('mec-') && !key.endsWith(CURRENT_VERSION))
        .map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

function isApiRequest(url) {
  return url.origin === self.location.origin && API_PREFIXES.some(prefix => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`));
}

function isStaticAsset(url) {
  return url.origin === self.location.origin && STATIC_EXTENSIONS.some(ext => url.pathname.endsWith(ext));
}

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, CACHE_NAME).catch(() => caches.match('/index.html')));
    return;
  }

  if (isApiRequest(url)) {
    // Somente GETs seguros entram em cache. Escritas continuam fora do service worker.
    event.respondWith(networkFirst(request, API_CACHE));
    return;
  }

  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(request, RUNTIME_CACHE));
    return;
  }
});
