"""Post phase — business owner submits a month-end close."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from .models import Post, TransactionStatus


# In-memory store (will be replaced by Supabase/Postgres)
_posts: dict[str, Post] = {}


def create_post(
    owner_id: str,
    business_name: str,
    period_end: str,
    deadline: str,
    budget_cents: int,
    description: str,
    chart_of_accounts: str | None = None,
    bank_statements: list[str] | None = None,
) -> Post:
    """Create a new month-end close post."""
    post = Post(
        owner_id=owner_id,
        business_name=business_name,
        period_end=period_end,
        deadline=deadline,
        budget_cents=budget_cents,
        description=description,
        chart_of_accounts=chart_of_accounts,
        bank_statements=bank_statements,
        status=TransactionStatus.POSTED,
    )
    _posts[post.post_id] = post
    return post


def get_post(post_id: str) -> Post | None:
    return _posts.get(post_id)


def list_posts(status: TransactionStatus | None = None) -> list[Post]:
    if status:
        return [p for p in _posts.values() if p.status == status]
    return list(_posts.values())


def update_post_status(post_id: str, status: TransactionStatus) -> Post:
    post = get_post(post_id)
    if not post:
        raise ValueError(f"Post not found: {post_id}")
    post.status = status
    post.updated_at = datetime.now(timezone.utc).isoformat()
    _posts[post_id] = post
    return post


def delete_post(post_id: str) -> bool:
    return _posts.pop(post_id, None) is not None
