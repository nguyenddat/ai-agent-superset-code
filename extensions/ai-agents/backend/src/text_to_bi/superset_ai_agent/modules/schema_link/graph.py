"""The Semantic Layer's schema graph, read into the shape the join path search walks.

A node is a base table, an edge an approved relationship from a foreign key column to the key it references. Walking
an edge the way the key points (many rows to one) keeps the measured rows as they are; walking it back (one to many)
repeats each row once per match, so its cost is high and the walk is flagged as fanning out. A one-to-one edge repeats
nothing either way.
"""

from dataclasses import dataclass, field
from typing import Any

FORWARD_COST = 1
# High enough that a path through one fan-out edge loses to any path of fewer than ten plain joins.
FANOUT_COST = 10


@dataclass(frozen=True)
class Edge:
    id: int
    from_table: int
    from_column: str
    to_table: int
    to_column: str
    cardinality: str


@dataclass(frozen=True)
class Step:
    """One edge as a path walks it: `forward` follows the key from `edge.from_table` to `edge.to_table`."""

    edge: Edge
    forward: bool

    @property
    def start(self) -> int:
        return self.edge.from_table if self.forward else self.edge.to_table

    @property
    def end(self) -> int:
        return self.edge.to_table if self.forward else self.edge.from_table

    @property
    def start_column(self) -> str:
        return self.edge.from_column if self.forward else self.edge.to_column

    @property
    def end_column(self) -> str:
        return self.edge.to_column if self.forward else self.edge.from_column

    @property
    def fanout(self) -> bool:
        return not self.forward and self.edge.cardinality != "one_to_one"

    @property
    def cost(self) -> int:
        return FANOUT_COST if self.fanout else FORWARD_COST


@dataclass
class SchemaGraph:
    dialect: str
    tables: dict[int, dict[str, Any]]
    edges: list[Edge]
    excluded: list[dict[str, Any]] = field(default_factory=list)
    # Every way each table's edges may be walked, cheapest first; built once, as path searches ask for it per table.
    _steps: dict[int, list[Step]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        steps: dict[int, list[Step]] = {}
        for edge in self.edges:
            steps.setdefault(edge.from_table, []).append(Step(edge, forward=True))
            steps.setdefault(edge.to_table, []).append(Step(edge, forward=False))
        self._steps = {
            table: sorted(found, key=lambda step: (step.cost, step.edge.id, not step.forward))
            for table, found in steps.items()
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SchemaGraph":
        tables = {table["dataset_id"]: table for table in payload.get("tables", [])}
        edges = [
            Edge(
                item["id"], item["from"]["dataset_id"], item["from"]["column"], item["to"]["dataset_id"],
                item["to"]["column"], item["cardinality"],
            )
            for item in payload.get("edges", [])
            if item["from"]["dataset_id"] in tables and item["to"]["dataset_id"] in tables
        ]
        dialect = (payload.get("database") or {}).get("dialect") or "postgresql"
        return cls(dialect=dialect, tables=tables, edges=edges, excluded=payload.get("excluded", []))

    def steps_from(self, table_id: int, allow_fanout: bool) -> list[Step]:
        """The steps leaving a table, every way an edge may be walked; fan-out steps only when allowed."""
        return [step for step in self._steps.get(table_id, []) if allow_fanout or not step.fanout]

    def column(self, table_id: int, name: str) -> dict[str, Any] | None:
        table = self.tables.get(table_id)
        return next((column for column in (table or {}).get("columns", []) if column["name"] == name), None)

    def table_name(self, table_id: int) -> str:
        return self.tables[table_id]["table"]
