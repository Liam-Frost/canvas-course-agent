from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import httpx


@dataclass(frozen=True)
class CanvasClient:
    base_url: str
    access_token: str

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=httpx.Timeout(30.0),
        )

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterable[dict[str, Any]]:
        """Yields items from Canvas-style pagination (Link header)."""
        params = params or {}
        url = path

        with self._client() as c:
            while True:
                r = c.get(url, params=params)
                r.raise_for_status()

                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        yield item
                else:
                    # Some endpoints return dicts; treat as single item
                    yield data

                # Follow Link rel="next"
                next_url = None
                link = r.headers.get("Link") or r.headers.get("link")
                if link:
                    parts = [p.strip() for p in link.split(",")]
                    for p in parts:
                        if 'rel="next"' in p or "rel=next" in p:
                            # format: <https://...>; rel="next"
                            start = p.find("<")
                            end = p.find(">", start + 1)
                            if start != -1 and end != -1:
                                next_url = p[start + 1 : end]
                            break

                if not next_url:
                    break

                url = next_url
                params = {}  # next_url already has params

    def get_self_profile(self) -> dict[str, Any]:
        with self._client() as c:
            r = c.get("/api/v1/users/self/profile")
            r.raise_for_status()
            return r.json()

    def list_courses(self, *, include_syllabus: bool = True, enrollment_state: str = "active") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if enrollment_state:
            params["enrollment_state"] = enrollment_state
        if include_syllabus:
            params["include[]"] = ["syllabus_body", "term", "course_image"]

        return list(self._paginate("/api/v1/courses", params=params))

    def list_calendar_events(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        type: str | None = None,
        context_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if type:
            params["type"] = type
        if context_codes:
            params["context_codes[]"] = context_codes

        return list(self._paginate("/api/v1/calendar_events", params=params))

    def get_course(self, course_id: int, *, include: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if include:
            params["include[]"] = include
        with self._client() as c:
            r = c.get(f"/api/v1/courses/{course_id}", params=params)
            r.raise_for_status()
            return r.json()

    def list_course_users(
        self,
        course_id: int,
        *,
        enrollment_types: list[str] | None = None,
        include: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if enrollment_types:
            params["enrollment_type[]"] = enrollment_types
        if include:
            params["include[]"] = include
        return list(self._paginate(f"/api/v1/courses/{course_id}/users", params=params))

    def list_modules(self, course_id: int, *, include_items: bool = True) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if include_items:
            params["include[]"] = ["items"]
        return list(self._paginate(f"/api/v1/courses/{course_id}/modules", params=params))

    def list_assignments(self, course_id: int, *, include: list[str] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if include:
            params["include[]"] = include
        return list(self._paginate(f"/api/v1/courses/{course_id}/assignments", params=params))

    def list_quizzes(self, course_id: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        return list(self._paginate(f"/api/v1/courses/{course_id}/quizzes", params=params))
