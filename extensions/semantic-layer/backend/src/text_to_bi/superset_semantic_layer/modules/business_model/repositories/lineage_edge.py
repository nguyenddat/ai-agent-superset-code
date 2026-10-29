from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import LineageEdge
from ..services.lineage_overrides import EdgeKey


class LineageEdgeRepository(BaseRepository[LineageEdge]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, LineageEdge)

    def between(self, dataset_ids: Iterable[int]) -> list[LineageEdge]:
        """Overrides whose both ends are among these datasets."""
        dataset_ids = list(dataset_ids)
        return self.session.scalars(
            select(LineageEdge).where(
                LineageEdge.source_dataset_id.in_(dataset_ids),
                LineageEdge.target_dataset_id.in_(dataset_ids),
            )
        ).all()

    def for_keys(self, key: EdgeKey, flipped: EdgeKey) -> list[LineageEdge]:
        """Overrides stored under an edge's key or under the key it has when its direction flips."""
        return list(
            self.session.scalars(
                select(LineageEdge).where(
                    LineageEdge.source_dataset_id.in_({key[0], flipped[0]}),
                    LineageEdge.target_dataset_id.in_({key[1], flipped[1]}),
                    LineageEdge.kind.in_({key[2], flipped[2]}),
                )
            )
        )
