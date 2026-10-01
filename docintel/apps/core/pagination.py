"""Cursor pagination. Counts are intentionally not computed."""

from __future__ import annotations

from rest_framework.pagination import CursorPagination


class CreatedAtDescCursorPagination(CursorPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = ("-created_at", "-id")


class CreatedAtAscCursorPagination(CursorPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = ("created_at", "id")
