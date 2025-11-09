import os
import sqlite3
import hashlib
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from src.utils.constants import CONFIG_DIR

DB_PATH = os.path.join(CONFIG_DIR, 'media_history.db')
PARTIAL_HASH_READ_BYTES = 4 * 1024 * 1024  # 4MB für Teil-Hash

class MediaHistoryStore:
    """Verwaltet Historie verarbeiteter Mediendateien (Backup/Import)."""

    _instance = None

    def __init__(self):
        self.db_path = DB_PATH
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute('PRAGMA journal_mode=WAL;')
        self.conn.execute('PRAGMA synchronous=NORMAL;')
        self._create_schema()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = MediaHistoryStore()
        return cls._instance

    def _create_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_hash TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                media_type TEXT NOT NULL CHECK(media_type IN ('video','photo')),
                first_seen_at TEXT NOT NULL,
                backed_up_at TEXT NULL,
                imported_at TEXT NULL,
                created_at TEXT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_processed_files_hash ON processed_files(identity_hash);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_processed_files_media_type ON processed_files(media_type);")
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ---------------- Identity -----------------

    def compute_identity(self, path: str) -> Optional[Tuple[str, int]]:
        """Berechnet (identity_hash, size_bytes) für eine Datei.
        identity_hash basiert auf Größe + Teil-Hash der ersten 4MB.
        """
        try:
            size = os.path.getsize(path)
            h = hashlib.sha1()
            h.update(str(size).encode('utf-8'))
            with open(path, 'rb') as f:
                chunk = f.read(PARTIAL_HASH_READ_BYTES)
                h.update(chunk)
            return h.hexdigest(), size
        except Exception as e:
            print(f"MediaHistory: Fehler beim Hash für {path}: {e}")
            return None

    # ---------------- Queries -----------------

    def contains(self, identity_hash: str) -> bool:
        """
        Prüft ob eine Datei bereits in der Historie ist (gesichert ODER importiert).

        Args:
            identity_hash: Der zu prüfende Hash

        Returns:
            True wenn vorhanden, sonst False
        """
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM processed_files WHERE identity_hash = ?", (identity_hash,))
        return cur.fetchone()[0] > 0

    def was_imported(self, identity_hash: str) -> bool:
        """
        Prüft ob eine Datei bereits importiert wurde (imported_at ist gesetzt).

        Unterschied zu contains(): Diese Methode prüft speziell ob die Datei
        bereits in die App importiert wurde, nicht nur gesichert.

        Args:
            identity_hash: Der zu prüfende Hash

        Returns:
            True wenn bereits importiert, sonst False
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT imported_at FROM processed_files WHERE identity_hash = ?",
            (identity_hash,)
        )
        row = cur.fetchone()
        # Datei wurde importiert wenn imported_at nicht NULL ist
        return row is not None and row[0] is not None

    def upsert(self, identity_hash: str, filename: str, size_bytes: int, media_type: str,
               backed_up_at: Optional[str] = None, imported_at: Optional[str] = None,
               created_at: Optional[str] = None):
        """Fügt neuen Eintrag hinzu oder aktualisiert Zeitstempel-Felder.
        first_seen_at bleibt beim ersten Insert erhalten.
        """
        now_iso = datetime.utcnow().isoformat(timespec='seconds')
        cur = self.conn.cursor()
        # Prüfe ob existiert
        cur.execute("SELECT id, first_seen_at, backed_up_at, imported_at FROM processed_files WHERE identity_hash=?", (identity_hash,))
        row = cur.fetchone()
        if row:
            # Update nur Felder die neu übergeben wurden (nicht überschreiben mit None)
            existing_first_seen = row[1]
            existing_backed = row[2]
            existing_imported = row[3]
            new_backed = backed_up_at if backed_up_at else existing_backed
            new_imported = imported_at if imported_at else existing_imported
            cur.execute(
                "UPDATE processed_files SET filename=?, size_bytes=?, media_type=?, backed_up_at=?, imported_at=?, created_at=? WHERE identity_hash=?",
                (filename, size_bytes, media_type, new_backed, new_imported, created_at, identity_hash)
            )
        else:
            cur.execute(
                "INSERT INTO processed_files (identity_hash, filename, size_bytes, media_type, first_seen_at, backed_up_at, imported_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (identity_hash, filename, size_bytes, media_type, now_iso, backed_up_at, imported_at, created_at)
            )
        self.conn.commit()

    def list_entries(self, limit: int = 1000, search: Optional[str] = None) -> List[Dict]:
        """
        Listet Einträge mit optionaler Suche nach Dateiname.
        Sortiert nach neuestem Import (imported_at), dann backed_up_at, dann first_seen_at.
        """
        cur = self.conn.cursor()
        if search:
            # Suche nach Dateiname (case-insensitive via LIKE)
            # Sortierung: imported_at DESC (mit NULL am Ende), dann backed_up_at, dann first_seen_at
            cur.execute(
                """SELECT id, filename, size_bytes, media_type, first_seen_at, backed_up_at, imported_at, created_at 
                   FROM processed_files 
                   WHERE filename LIKE ? 
                   ORDER BY 
                     CASE WHEN imported_at IS NULL THEN 1 ELSE 0 END,
                     imported_at DESC,
                     backed_up_at DESC,
                     first_seen_at DESC
                   LIMIT ?""",
                (f"%{search}%", limit)
            )
        else:
            cur.execute(
                """SELECT id, filename, size_bytes, media_type, first_seen_at, backed_up_at, imported_at, created_at 
                   FROM processed_files 
                   ORDER BY 
                     CASE WHEN imported_at IS NULL THEN 1 ELSE 0 END,
                     imported_at DESC,
                     backed_up_at DESC,
                     first_seen_at DESC
                   LIMIT ?""",
                (limit,)
            )
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                'id': r[0],
                'filename': r[1],
                'size_bytes': r[2],
                'media_type': r[3],
                'first_seen_at': r[4],
                'backed_up_at': r[5],
                'imported_at': r[6],
                'created_at': r[7]
            })
        return result

    def delete_by_ids(self, ids: List[int]):
        if not ids:
            return
        cur = self.conn.cursor()
        placeholders = ','.join('?' for _ in ids)
        cur.execute(f"DELETE FROM processed_files WHERE id IN ({placeholders})", ids)
        self.conn.commit()

    def purge_all(self):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM processed_files")
        self.conn.commit()

# Convenience Funktionen

def get_media_type_from_filename(filename: str) -> str:
    lower = filename.lower()
    video_exts = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.webm')
    photo_exts = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif', '.webp', '.heic', '.raw', '.cr2', '.nef', '.arw', '.dng')
    if lower.endswith(video_exts):
        return 'video'
    if lower.endswith(photo_exts):
        return 'photo'
    # Default
    return 'video'

