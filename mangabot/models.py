from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MangaBranch:
    id: int
    count_chapters: int


@dataclass
class MangaChapter:
    id: int
    chapter_label: str
    name: str
    index: int
    tome: int
    is_paid: bool

    @property
    def display_name(self) -> str:
        base = f"Том {self.tome}, глава {self.chapter_label}"
        if self.name:
            base += f" - {self.name}"
        if self.is_paid:
            base += " (платная)"
        return base


@dataclass
class MangaTitle:
    id: int
    dir_name: str
    title: str
    secondary_title: str
    cover_url: str
    status_name: str
    type_name: str
    issue_year: Optional[int]
    branch: MangaBranch

    @property
    def site_url(self) -> str:
        return f"https://remanga.org/manga/{self.dir_name}/main"
