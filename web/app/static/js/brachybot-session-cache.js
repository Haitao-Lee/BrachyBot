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
    var _runningSize = 0;
    var _sizeInitialized = false;
    var _sizeInitialization = null;

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
            var oldSize = 0;
            var getReq = store.get(key);
            getReq.onerror = function () { reject(getReq.error); };
            getReq.onsuccess = function () {
                oldSize = Number(getReq.result && getReq.result.size) || 0;
                store.put({
                    sessionId: key[0], ns: key[1], key: key[2],
                    data: data, size: data.byteLength, timestamp: Date.now(),
                });
            };
            tx.oncomplete = function () { resolve(data.byteLength - oldSize); };
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
            var deletedBytes = 0;
            store.openCursor(keyRange).onsuccess = function (e) {
                var cursor = e.target.result;
                if (cursor) {
                    deletedBytes += Number(cursor.value && cursor.value.size) || 0;
                    cursor.delete();
                    cursor.continue();
                } else { resolve(deletedBytes); }
            };
            tx.onerror = function () { resolve(0); };
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

    async function ensureRunningSize(db) {
        if (_sizeInitialized) return;
        if (_sizeInitialization) return _sizeInitialization;
        _sizeInitialization = dbGetAll(db).then(function (entries) {
            _runningSize = entries.reduce(function (total, entry) {
                return total + (Number(entry.size) || 0);
            }, 0);
            _sizeInitialized = true;
        }).catch(function () {
            // Cache accounting must never block a clinical restore.
            _sizeInitialized = true;
        }).finally(function () { _sizeInitialization = null; });
        return _sizeInitialization;
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
        var db = await openDB();
        if (!db) return;
        await ensureRunningSize(db);
        if (_runningSize <= MAX_BYTES) return;
        try {
            var entries = await dbGetAll(db);
            entries.sort(function (a, b) { return a.timestamp - b.timestamp; });
            var toFree = _runningSize - MAX_BYTES;
            var evicted = 0;
            for (var i = 0; i < entries.length - 4 && toFree > 0; i++) {
                var deleted = await dbDeleteAll(db, entries[i].key);
                toFree -= deleted;
                evicted += deleted;
            }
            _runningSize = Math.max(0, _runningSize - evicted);
        } catch (_) {}
    }

    var api = {
        get: async function (sessionId, ns, key) {
            var db = await openDB();
            if (!db) return null;
            await ensureRunningSize(db);
            // Return as soon as IndexedDB responds. The previous code started
            // dbGet() but always slept for the full timeout on every cache hit.
            return Promise.race([
                dbGet(db, [sessionId, ns, key]),
                new Promise(function (resolve) {
                    setTimeout(function () { resolve(null); }, CACHE_GET_TIMEOUT_MS);
                }),
            ]);
        },
        put: async function (sessionId, ns, key, data) {
            var db = await openDB();
            if (!db) return;
            await ensureRunningSize(db);
            var delta = await dbPut(db, [sessionId, ns, key], data);
            _runningSize = Math.max(0, _runningSize + delta);
            scheduleEviction();
        },
        invalidateSession: async function (sessionId) {
            var db = await openDB();
            if (!db) return;
            await ensureRunningSize(db);
            var deleted = await dbDeleteAll(db, IDBKeyRange.bound([sessionId, '', ''], [sessionId, '\uffff', '\uffff']));
            _runningSize = Math.max(0, _runningSize - deleted);
        },
        invalidateAll: async function () {
            var db = await openDB();
            if (!db) return;
            await dbDeleteAll(db, null);
            _runningSize = 0;
            _sizeInitialized = true;
        },
        estimatedSize: function () { return _runningSize; },
    };

    window.SessionCache = api;
    window._sessionCache = api;
})();
