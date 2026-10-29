from superset import db

from .repositories.glossary_term import GlossaryTermRepository
from .repositories.glossary_term_audit_event import GlossaryTermAuditEventRepository
from .repositories.glossary_term_link import GlossaryTermLinkRepository
from .repositories.glossary_term_revision import GlossaryTermRevisionRepository


def glossary_term_repository() -> GlossaryTermRepository:
    return GlossaryTermRepository(db.session)


def glossary_term_revision_repository() -> GlossaryTermRevisionRepository:
    return GlossaryTermRevisionRepository(db.session)


def glossary_term_link_repository() -> GlossaryTermLinkRepository:
    return GlossaryTermLinkRepository(db.session)


def glossary_term_audit_event_repository() -> GlossaryTermAuditEventRepository:
    return GlossaryTermAuditEventRepository(db.session)
