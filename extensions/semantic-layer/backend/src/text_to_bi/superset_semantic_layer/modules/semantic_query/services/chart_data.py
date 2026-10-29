import logging

from superset.connectors.sqla.models import SqlaTable

from ....core.security import is_superset_access_error
from ...data_dictionary.models import ColumnDictionary
from .members import build_values_payload, coded_value_columns, coded_values_from_rows

logger = logging.getLogger(__name__)


def coded_values(dataset: SqlaTable, entries: dict[str, ColumnDictionary]) -> dict[str, list[str]]:
    """The stored values of each code column, read through ChartData as the caller; free text is left out."""
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    columns = coded_value_columns(dataset, entries)
    if not columns:
        return {}
    try:
        command = ChartDataCommand(ChartDataQueryContextSchema().load(build_values_payload(dataset, columns)))
        command.validate()
        results = command.run()["queries"]
    except Exception as ex:
        if not is_superset_access_error(ex):
            logger.exception("Reading the coded values of %s failed", dataset.table_name)
        return {}
    coded = {}
    for name, result in zip(columns, results):
        values = None if result.get("error") else coded_values_from_rows(result.get("data", []), name)
        if values:
            coded[name] = values
    return coded
