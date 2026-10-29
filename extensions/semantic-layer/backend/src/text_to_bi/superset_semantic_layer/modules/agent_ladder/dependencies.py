from superset import db

from .repositories.dataset_proposal import DatasetProposalRepository


def dataset_proposal_repository() -> DatasetProposalRepository:
    return DatasetProposalRepository(db.session)
