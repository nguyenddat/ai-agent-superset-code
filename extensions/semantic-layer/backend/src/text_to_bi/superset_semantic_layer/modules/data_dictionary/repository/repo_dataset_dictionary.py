from sqlalchemy.orm import Session

from ....common import BaseRepository
from ....models.dataset_dictionary import DatasetDictionary


class DatasetDictionaryRepository(BaseRepository[DatasetDictionary]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetDictionary)
