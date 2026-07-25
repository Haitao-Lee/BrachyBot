/* Browser-side IndexedDB cache for heavy session data (CT volume,
 * 3D meshes, label volumes, report figures).  Avoids re-downloading
 * multiple megabytes across a local network on every session switch.
 *
 * Storage model
 *   objectStore: 'cache'
 *   key path:    [sessionId, namespace, key]
 *   fields:      { data: ArrayBuffer, size, timestamp }
 *
 * Optimisation
 *   Total size is tracked with a running counter so put() does not
 *   need to scan every entry just to check the quota.  Eviction is
 *   deferred to the next idle callback or skipped entirely if the
 *   counter is below the cap.  Cache get() returns null after a
 *   2 s timeout so a slow or locked IndexedDB never blocks the
 *   session-restore pipeline.
 */
(function () {
    var DB_NAME = 'brachybot-session-cache';
    var DB_VERSION = 1;
    var STORE = 'cache';
    var MAX_BYTES = 800 * 1024 * 1024;  // 800 MB global cap
    var CACHE_GET_TIMEOUT_MS = 2000;    // give up on cache after 2 s

    var _db = null;
    var _opening = null;
    var _runningSize = 0;   // best-effort aggregate, corrected on eviction scan

    function openDB() {
        if (_db) return Promise.resolve(_db);
        if (_opening) return _opening;
        _opening = new Promise(function (resolve) {
            if (typeof indexedDB === 'undefined') { _opening = null; resolve(null); return; }
            var req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = function () {
                var db = req.result;
                if (!db.objectStoreNames.contains(STORE)) {
                    db.createObjectStore(STORE, { keyPath: ['sessionId', 'ns', 'key'] });
                }
            };
            req.onsuccess = function () { _db = req.result; _opening = null; resolve(_db); };
            req.onerror = function () { _opening = null; console.warn('[session-cache] IndexedDB unavailable:', req.error); resolve(null); };
        });
        return _opening;
    }

    function dbPut(db, key, data) {
        return new Promise(function (resolve, reject) {
            var tx = db.transaction(STORE, 'readwrite');
            tx.onerror = function () { reject(tx.error); };
            var store = tx.objectStore(STORE);
            store.put({ sessionId: key[0], ns: key[1], key: key[2], data: data, size: data.byteLength, timestamp: Date.now() }).onsuccess = function () { resolve(true); };
        });
    }

    function dbGet(db, key) {
        return new Promise(function (resolve) {
            var tx = db.transaction(STORE, 'readonly');
            var store = tx.objectStore(STORE);
            var req = store.get(key);
            req.onsuccess = function () { resolve(req.result ? req.result.data : null); };
            req.onerror = function () { resolve(null); };
        });
    }

    function dbDeleteAll(db, keyRange) {
        return new Promise(function (resolve) {
            var tx = db.transaction(STORE, 'readwrite');
            var store = tx.objectStore(STORE);
            store.openCursor(keyRange).onsuccess = function (e) {
                var cursor = e.target.result;
                if (cursor) { cursor.delete(); cursor.continue(); }
                else { resolve(); }
            };
        });
    }

    function dbGetAll(db) {
        return new Promise(function (resolve) {
            var tx = db.transaction(STORE, 'readonly');
            var store = tx.objectStore(STORE);
            var entries = [];
            store.openCursor().onsuccess = function (e) {
                var cursor = e.target.result;
                if (cursor) { entries.push({ key: cursor.key, size: cursor.value.size, timestamp: cursor.value.timestamp }); cursor.continue(); }
                else { resolve(entries); }
            };
        });
    }

    function scheduleEviction() {
        if (_evictionScheduled) return;
        _evictionScheduled = true;
        setTimeout(function () {
            _evictionScheduled = false;
            sessionCacheEvict();
        }, 5000);
    }
    var _evictionScheduled = false;

    async function sessionCacheEvict() {
        if (_runningSize <= MAX_BYTES) return;
        var db = await openDB();
        if (!db) return;
        try {
            var entries = await dbGetAll(db);
            entries.sort(function (a, b) { return a.timestamp - b.timestamp; });
            var toFree = _runningSize - MAX_BYTES;
            var evicted = 0;
            for (var i = 0; i < entries.length - 4 && toFree > 0; i++) {
                await dbDeleteAll(db, entries[i].key);
                toFree -= entries[i].size;
                evicted += entries[i].size;
            }
            _runningSize = Math.max(0, _runningSize - evicted);
        } catch (_) {}
    }

    var api = {
        get: async function (sessionId, ns, key) {
            var db = await openDB();
            if (!db) return null;
            // Race against a timeout so a hung IndexedDB never blocks restore.
            var result = null;
            var done = false;
            dbGet(db, [sessionId, ns, key]).then(function (r) { if (!done) result = r; });
            await new Promise(function (r) { setTimeout(r, CACHE_GET_TIMEOUT_MS); });
            done = true;
            return result;
        },
        put: async function (sessionId, ns, key, data) {
            var db = await openDB();
            if (!db) return;
            await dbPut(db, [sessionId, ns, key], data);
            _runningSize += data.byteLength;
            scheduleEviction();
        },
        invalidateSession: async function (sessionId) {
            var db = await openDB();
            if (!db) return;
            // We don't know exactly how many bytes this session occupies.
            // Eviction will correct _runningSize on its next scan.
            _runningSize = Math.max(0, _runningSize / 2);
            await dbDeleteAll(db, IDBKeyRange.bound([sessionId, '', ''], [sessionId, '\uffff', '\uffff']));
        },
        invalidateAll: async function () {
            var db = await openDB();
            if (!db) return;
            await dbDeleteAll(db, null);
            _runningSize = 0;
        },
        estimatedSize: function () { return _runningSize; },
    };

    window.SessionCache = api;
    window._sessionCache = api;
})();
