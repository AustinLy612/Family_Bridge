"""Site settings (help contacts, service hours) — Plan §5.1/§5.2, O4 placeholders."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import SiteHelp
from app.models import Setting, Site

HELP_CONFIRMED_KEY = "site.help_contacts_confirmed"


def get_site(db: Session) -> Site | None:
    return db.execute(select(Site).order_by(Site.updated_at).limit(1)).scalar_one_or_none()


def help_confirmed(db: Session) -> bool:
    row = db.get(Setting, HELP_CONFIRMED_KEY)
    return bool(row and row.value is True)


def site_help(db: Session) -> SiteHelp:
    site = get_site(db)
    if site is None:
        return SiteHelp(name="", help_contacts=[], service_hours={}, placeholder=True)
    return SiteHelp(
        name=site.name,
        help_contacts=list(site.help_contacts or []),
        service_hours=dict(site.service_hours or {}),
        placeholder=not help_confirmed(db),
    )
