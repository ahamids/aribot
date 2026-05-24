"use client";

import type { WrappedKey } from "./wrap";

/**
 * IndexedDB persistence of the passphrase-wrapped vault secret key.
 * Scoped per Supabase user_id, so multiple users on the same browser
 * (separate profiles or shared family device) don't clash.
 *
 * Schema:
 *   db:    "aribot-vault"
 *   store: "wrapped-keys"
 *   key:   user_id (uuid string)
 *   value: WrappedKey
 *
 * IndexedDB keeps data per-origin and survives normal reloads but is
 * wiped by:
 *   - "Clear browsing data → cookies and site data"
 *   - Incognito session ending
 *   - Profile deletion
 *
 * That's exactly why we ALSO store a recovery-code-wrapped copy in
 * Supabase: so a wipe is recoverable.
 */

const DB_NAME = "aribot-vault";
const DB_VERSION = 1;
const STORE_NAME = "wrapped-keys";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T> | Promise<T>,
): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, mode);
      const store = tx.objectStore(STORE_NAME);
      const out = fn(store);
      if (out instanceof IDBRequest) {
        out.onsuccess = () => resolve(out.result);
        out.onerror = () => reject(out.error);
      } else {
        out.then(resolve, reject);
      }
    });
  } finally {
    db.close();
  }
}

export async function saveWrappedKey(
  userId: string,
  wrapped: WrappedKey,
): Promise<void> {
  await withStore("readwrite", (store) => store.put(wrapped, userId));
}

export async function loadWrappedKey(
  userId: string,
): Promise<WrappedKey | null> {
  const result = await withStore<WrappedKey | undefined>("readonly", (store) =>
    store.get(userId),
  );
  return result ?? null;
}

export async function clearWrappedKey(userId: string): Promise<void> {
  await withStore("readwrite", (store) => store.delete(userId));
}

export async function hasWrappedKey(userId: string): Promise<boolean> {
  return (await loadWrappedKey(userId)) !== null;
}
