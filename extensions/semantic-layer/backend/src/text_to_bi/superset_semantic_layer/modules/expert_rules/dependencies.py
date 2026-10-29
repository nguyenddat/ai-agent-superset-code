from superset import db

from .repositories.expert_rule import ExpertRuleRepository
from .repositories.expert_rule_audit_event import ExpertRuleAuditEventRepository
from .repositories.expert_rule_link import ExpertRuleLinkRepository
from .repositories.expert_rule_revision import ExpertRuleRevisionRepository


def expert_rule_repository() -> ExpertRuleRepository:
    return ExpertRuleRepository(db.session)


def expert_rule_revision_repository() -> ExpertRuleRevisionRepository:
    return ExpertRuleRevisionRepository(db.session)


def expert_rule_link_repository() -> ExpertRuleLinkRepository:
    return ExpertRuleLinkRepository(db.session)


def expert_rule_audit_event_repository() -> ExpertRuleAuditEventRepository:
    return ExpertRuleAuditEventRepository(db.session)
