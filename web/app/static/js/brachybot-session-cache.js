/* Browser-side IndexedDB cache for heavy session data (CT volume,
 * 3D meshes, label volumes, report figures).  Avoids re-downloading
 * multiple megabytes across a local network on every session switch.
 *
 * Storage model
 *   objectStore: 'cache'
 *   key path:    [sessionId, namespace, key]
 *   fields:      { data: ArrayBuffer, size, timestamp }
 *
 * LRU eviction
 *    Enforced on every put().  When totalSize > MAX_BYTES the oldest
 *    entries (by timestamp) are deleted until we are below the limit.
 */
(function () {
    const DB_NAME = 'brachybot-session-cache';
    const DB_VERSION = 1;
    const STORE = 'cache';
    const MAX_BYTES = 800 * 1024 * 1024;  // 800 MB global cap
    const MIN_ENTRIES = 4;                // keep at least this many before evicting

    let _db = null;
    let _opening = null;

    function openDB() {
        if (_db) return Promise.resolve(_db);
        if (_opening) return _opening;
        _opening = new Promise((resolve, reject) => {
            if (typeof indexedDB === 'undefined') {
                _opening = null;
                resolve(null);
                return;
            }
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = function () {
                const db = req.result;
                if (!db.objectStoreNames.contains(STORE)) {
                    db.createObjectStore(STORE, { keyPath: ['sessionId', 'ns', 'key'] });
                }
            };
            req.onsuccess = function () {
                _db = req.result;
                _opening = null;
                resolve(_db);
            };
            req.onerror = function () {
                _opening = null;
                console.warn('[session-cache] IndexedDB unavailable:', req.error);
                resolve(null);
            };
        });
        return _opening;
    }

    function dbPut(db, key, data) {
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, 'readwrite');
            tx.onerror = () => reject(tx.error);
            const store = tx.objectStore(STORE);
            store.put({
                sessionId: key[0], ns: key[1], key: key[2],
                data: data, size: data.byteLength, timestamp: Date.now(),
            }).onsuccess = () => resolve(true);
        });
    }

    function dbGet(db, key) {
        return new Promise((resolve) => {
            const tx = db.transaction(STORE, 'readonly');
            const store = tx.objectStore(STORE);
            const req = store.get(key);
            req.onsuccess = () => resolve(req.result ? req.result.data : null);
            req.onerror = () => resolve(null);
        });
    }

    function dbDeleteAll(db, keyRange) {
        return new Promise((resolve) => {
            const tx = db.transaction(STORE, 'readwrite');
            const store = tx.objectStore(STORE);
            store.openCursor(keyRange).onsuccess = function (e) {
                const cursor = e.target.result;
                if (cursor) { cursor.delete(); cursor.continue(); }
                else { resolve(); }
            };
        });
    }

    function dbGetAll(db) {
        return new Promise((resolve) => {
            const tx = db.transaction(STORE, 'readonly');
            const store = tx.objectStore(STORE);
            const entries = [];
            store.openCursor().onsuccess = function (e) {
                const cursor = e.target.result;
                if (cursor) {
                    entries.push({ key: cursor.key, size: cursor.value.size, timestamp: cursor.value.timestamp });
                    cursor.continue();
                } else {
                    resolve(entries);
                }
            };
        });
    }

    async function evictIfNeeded(db, totalSize) {
        if (totalSize <= MAX_BYTES) return;
        const entries = await dbGetAll(db);
        entries.sort((a, b) => a.timestamp - b.timestamp);
        let toFree = totalSize - MAX_BYTES;
        for (let i = 0; i < entries.length - MIN_ENTRIES && toFree > 0; i++) {
            await dbDeleteAll(db, entries[i].key);
            toFree -= entries[i].size;
        }
    }

    async function getTotalSize(db) {
        const entries = await dbGetAll(db);
        return entries.reduce((sum, e) => sum + e.size, 0);
    }

    const api = {
        async get(sessionId, ns, key) {
            const db = await openDB();
            if (!db) return null;
            return dbGet(db, [sessionId, ns, key]);
        },
        async put(sessionId, ns, key, data) {
            const db = await openDB();
            if (!db) return;
            await dbPut(db, [sessionId, ns, key], data);
            const total = await getTotalSize(db);
            await evictIfNeeded(db, total);
        },
        async invalidateSession(sessionId) {
            const db = await openDB();
            if (!db) return;
            await dbDeleteAll(db, IDBKeyRange.bound([sessionId, '', ''], [sessionId, '\uffff', '\uffff']));
        },
        async invalidateAll() {
            const db = await openDB();
            if (!db) return;
            await dbDeleteAll(db, null);
        },
        async estimatedSize() {
            const db = await openDB();
            if (!db) return 0;
            return getTotalSize(db);
        },
    };

    window.SessionCache = api;
    window._sessionCache = api; // alias for backward compat
})();
