from __future__ import annotations

from typing import Any
from typing import Dict, Optional

import aiohttp

from .models import MangaBranch, MangaChapter, MangaTitle


API_BASE = "https://api.remanga.org/api"
SITE_BASE = "https://remanga.org"


def _absolute_media_url(value: Optional[str]) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"{SITE_BASE}{value}"
    return f"{SITE_BASE}/{value}"


class ReMangaClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def _get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        async with self.session.get(f"{API_BASE}{path}", params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def search_titles(self, query: str, limit: int = 6) -> list[MangaTitle]:
        payload = await self._get_json(
            "/search/",
            params={"query": query, "page": 1, "count": limit, "field": "titles"},
        )
        results: list[MangaTitle] = []
        for item in payload.get("content", []):
            branch = MangaBranch(id=0, count_chapters=int(item.get("count_chapters") or 0))
            results.append(
                MangaTitle(
                    id=int(item["id"]),
                    dir_name=item["dir"],
                    title=item.get("rus_name") or item.get("main_name") or item["dir"],
                    secondary_title=item.get("secondary_name") or "",
                    cover_url=_absolute_media_url((item.get("img") or item.get("cover") or {}).get("high")),
                    status_name=(item.get("status") or {}).get("name") or "",
                    type_name=item.get("type") if isinstance(item.get("type"), str) else "",
                    issue_year=item.get("issue_year"),
                    branch=branch,
                )
            )
        return results

    async def get_title(self, dir_name: str) -> MangaTitle:
        payload = await self._get_json(f"/titles/{dir_name}/")
        content = payload["content"]
        branches = content.get("branches") or []
        if not branches:
            raise RuntimeError("У тайтла не найдено ни одной ветки с главами.")

        first_branch = branches[0]
        return MangaTitle(
            id=int(content["id"]),
            dir_name=content["dir"],
            title=content.get("rus_name") or content.get("main_name") or content["dir"],
            secondary_title=content.get("secondary_name") or "",
            cover_url=_absolute_media_url((content.get("img") or content.get("cover") or {}).get("high")),
            status_name=(content.get("status") or {}).get("name") or "",
            type_name=(content.get("type") or {}).get("name") or "",
            issue_year=content.get("issue_year"),
            branch=MangaBranch(
                id=int(first_branch["id"]),
                count_chapters=int(first_branch.get("count_chapters") or 0),
            ),
        )

    async def get_chapters(
        self,
        branch_id: int,
        page: int = 1,
        count: int = 30,
        ordering: str = "-index",
    ) -> list[MangaChapter]:
        payload = await self._get_json(
            "/titles/chapters/",
            params={
                "branch_id": branch_id,
                "ordering": ordering,
                "page": page,
                "count": count,
                "user_data": 0,
            },
        )
        chapters: list[MangaChapter] = []
        for item in payload.get("content", []):
            chapters.append(
                MangaChapter(
                    id=int(item["id"]),
                    chapter_label=str(item.get("chapter") or item.get("index") or "?"),
                    name=item.get("name") or "",
                    index=int(item.get("index") or 0),
                    tome=int(item.get("tome") or 1),
                    is_paid=bool(item.get("is_paid")),
                )
            )
        return chapters

    async def get_latest_chapter(self, branch_id: int) -> Optional[MangaChapter]:
        chapters = await self.get_chapters(branch_id=branch_id, page=1, count=1)
        return chapters[0] if chapters else None

    async def get_latest_chapters(self, branch_id: int, limit: int = 10) -> list[MangaChapter]:
        chapters = await self.get_chapters(branch_id=branch_id, page=1, count=max(limit, 10))
        return chapters[:limit]

    async def find_chapter(
        self,
        branch_id: int,
        query: str,
        max_pages: int = 20,
    ) -> Optional[MangaChapter]:
        normalized = query.strip().lower().replace(",", ".")
        if not normalized:
            return None

        for page in range(1, max_pages + 1):
            chapters = await self.get_chapters(branch_id=branch_id, page=page, count=100)
            if not chapters:
                return None

            for chapter in chapters:
                if normalized == str(chapter.index).lower():
                    return chapter
                if normalized == chapter.chapter_label.lower().replace(",", "."):
                    return chapter

            if len(chapters) < 100:
                return None

        return None
