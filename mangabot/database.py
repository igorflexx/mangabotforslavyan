from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Iterable, Optional

from .models import MangaChapter, MangaTitle


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS manga (
                id INTEGER PRIMARY KEY,
                dir_name TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                secondary_title TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                site_url TEXT NOT NULL,
                branch_id INTEGER NOT NULL,
                status_name TEXT NOT NULL DEFAULT '',
                type_name TEXT NOT NULL DEFAULT '',
                issue_year INTEGER,
                latest_chapter_id INTEGER,
                latest_chapter_index INTEGER,
                latest_chapter_label TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                manga_id INTEGER NOT NULL,
                last_read_chapter_id INTEGER,
                last_read_chapter_index INTEGER NOT NULL DEFAULT 0,
                last_read_chapter_label TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, manga_id),
                FOREIGN KEY (manga_id) REFERENCES manga(id) ON DELETE CASCADE
            );
            """
        )
        self.connection.commit()

    def upsert_manga(self, manga: MangaTitle, latest_chapter: Optional[MangaChapter]) -> None:
        self.connection.execute(
            """
            INSERT INTO manga (
                id, dir_name, title, secondary_title, cover_url, site_url,
                branch_id, status_name, type_name, issue_year,
                latest_chapter_id, latest_chapter_index, latest_chapter_label
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                dir_name = excluded.dir_name,
                title = excluded.title,
                secondary_title = excluded.secondary_title,
                cover_url = excluded.cover_url,
                site_url = excluded.site_url,
                branch_id = excluded.branch_id,
                status_name = excluded.status_name,
                type_name = excluded.type_name,
                issue_year = excluded.issue_year,
                latest_chapter_id = excluded.latest_chapter_id,
                latest_chapter_index = excluded.latest_chapter_index,
                latest_chapter_label = excluded.latest_chapter_label
            """,
            (
                manga.id,
                manga.dir_name,
                manga.title,
                manga.secondary_title,
                manga.cover_url,
                manga.site_url,
                manga.branch.id,
                manga.status_name,
                manga.type_name,
                manga.issue_year,
                latest_chapter.id if latest_chapter else None,
                latest_chapter.index if latest_chapter else None,
                latest_chapter.chapter_label if latest_chapter else "",
            ),
        )
        self.connection.commit()

    def add_subscription(self, user_id: int, manga_id: int) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO subscriptions (
                user_id, manga_id, last_read_chapter_id, last_read_chapter_index, last_read_chapter_label
            )
            VALUES (?, ?, NULL, 0, '')
            """,
            (user_id, manga_id),
        )
        self.connection.commit()

    def delete_subscription(self, user_id: int, manga_id: int) -> None:
        self.connection.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND manga_id = ?",
            (user_id, manga_id),
        )
        self.connection.commit()

    def get_user_subscriptions(self, user_id: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
                m.id AS manga_id,
                m.dir_name,
                m.title,
                m.secondary_title,
                m.cover_url,
                m.site_url,
                m.branch_id,
                m.status_name,
                m.type_name,
                m.issue_year,
                m.latest_chapter_id,
                m.latest_chapter_index,
                m.latest_chapter_label,
                s.last_read_chapter_id,
                s.last_read_chapter_index,
                s.last_read_chapter_label
            FROM subscriptions s
            JOIN manga m ON m.id = s.manga_id
            WHERE s.user_id = ?
            ORDER BY m.title COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        return list(rows)

    def get_subscription(self, user_id: int, manga_id: int) -> Optional[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                m.id AS manga_id,
                m.dir_name,
                m.title,
                m.secondary_title,
                m.cover_url,
                m.site_url,
                m.branch_id,
                m.status_name,
                m.type_name,
                m.issue_year,
                m.latest_chapter_id,
                m.latest_chapter_index,
                m.latest_chapter_label,
                s.last_read_chapter_id,
                s.last_read_chapter_index,
                s.last_read_chapter_label
            FROM subscriptions s
            JOIN manga m ON m.id = s.manga_id
            WHERE s.user_id = ? AND s.manga_id = ?
            """,
            (user_id, manga_id),
        ).fetchone()

    def update_read_progress(self, user_id: int, manga_id: int, chapter: MangaChapter) -> None:
        self.connection.execute(
            """
            UPDATE subscriptions
            SET
                last_read_chapter_id = ?,
                last_read_chapter_index = ?,
                last_read_chapter_label = ?
            WHERE user_id = ? AND manga_id = ?
            """,
            (chapter.id, chapter.index, chapter.chapter_label, user_id, manga_id),
        )
        self.connection.commit()

    def update_latest_chapter(self, manga_id: int, chapter: MangaChapter) -> None:
        self.connection.execute(
            """
            UPDATE manga
            SET
                latest_chapter_id = ?,
                latest_chapter_index = ?,
                latest_chapter_label = ?
            WHERE id = ?
            """,
            (chapter.id, chapter.index, chapter.chapter_label, manga_id),
        )
        self.connection.commit()

    def list_tracked_manga(self) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
                m.*,
                COUNT(s.user_id) AS subscribers_count
            FROM manga m
            JOIN subscriptions s ON s.manga_id = m.id
            GROUP BY m.id
            ORDER BY m.title COLLATE NOCASE
            """
        ).fetchall()
        return list(rows)

    def list_subscribers_for_manga(self, manga_id: int) -> Iterable[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                s.user_id,
                s.last_read_chapter_id,
                s.last_read_chapter_index,
                s.last_read_chapter_label,
                m.title,
                m.site_url,
                m.latest_chapter_label
            FROM subscriptions s
            JOIN manga m ON m.id = s.manga_id
            WHERE s.manga_id = ?
            """,
            (manga_id,),
        ).fetchall()
