"""Join paths: the smallest tree of approved relationships that reaches every table a query needs from its root.

The root is the table holding the measured rows. First, Dijkstra from the root walks only steps that repeat no row
(many to one, and one to one either way); in a snowflake of catalogs and business tables the union of the shortest
paths to every needed table is then already a tree, and most questions end there. When some table cannot be reached
that way, the search falls back to a directed Steiner tree over every step, fan-out steps costing `FANOUT_COST`:
Dreyfus–Wagner, exact, up to `EXACT_TERMINALS` tables to reach, and the Takahashi–Matsuyama heuristic beyond.

Paths are directed because direction decides whether a join repeats rows, so the undirected Kou–Markowsky–Berman
approximation would not tell a safe join from a fanning-out one.
"""

import heapq
from dataclasses import dataclass, field
from itertools import count

from .graph import SchemaGraph, Step

EXACT_TERMINALS = 6
MAX_ALTERNATIVES = 3
INFINITY = float("inf")


class NoJoinPath(ValueError):
    """Some needed table is not reachable from the root through approved relationships."""

    def __init__(self, unreachable: list[int]) -> None:
        super().__init__("No approved relationships connect every needed table.")
        self.unreachable = unreachable


@dataclass
class JoinTree:
    root: int
    # From the root outward, so every step starts at a table already joined.
    steps: list[Step]
    algorithm: str
    # For a table reached by several paths of the same cost: each path as its edge IDs, the chosen one first.
    alternatives: dict[int, list[list[int]]] = field(default_factory=dict)

    @property
    def cost(self) -> int:
        return sum(step.cost for step in self.steps)

    @property
    def fanout(self) -> bool:
        return any(step.fanout for step in self.steps)

    @property
    def tables(self) -> list[int]:
        return [self.root, *(step.end for step in self.steps)]


def _shortest_paths(graph: SchemaGraph, source: int, allow_fanout: bool):
    """Dijkstra from `source`: the cost of each table, the step that reached it, and how many cheapest paths do."""
    cost = {source: 0}
    reached_by: dict[int, Step] = {}
    paths = {source: 1}
    order = count()
    queue = [(0, next(order), source)]
    done = set()
    while queue:
        current_cost, _order, table = heapq.heappop(queue)
        if table in done:
            continue
        done.add(table)
        for step in graph.steps_from(table, allow_fanout):
            candidate = current_cost + step.cost
            if candidate < cost.get(step.end, INFINITY):
                cost[step.end], reached_by[step.end], paths[step.end] = candidate, step, paths[table]
                heapq.heappush(queue, (candidate, next(order), step.end))
            elif candidate == cost.get(step.end) and step.end not in done:
                paths[step.end] += paths[table]
    return cost, reached_by, paths


def _path_to(reached_by: dict[int, Step], source: int, target: int) -> list[Step]:
    steps = []
    while target != source:
        step = reached_by[target]
        steps.append(step)
        target = step.start
    return steps[::-1]


def _alternatives(graph: SchemaGraph, root: int, target: int, cost: dict[int, float], allow_fanout: bool):
    """Up to `MAX_ALTERNATIVES` cheapest paths from the root to `target`, as edge IDs."""
    found: list[list[int]] = []

    def walk(table: int, path: list[int]) -> None:
        if len(found) >= MAX_ALTERNATIVES:
            return
        if table == target:
            found.append(path)
            return
        for step in graph.steps_from(table, allow_fanout):
            if cost.get(step.end) == cost[table] + step.cost and cost.get(step.end, INFINITY) <= cost[target]:
                walk(step.end, [*path, step.edge.id])

    walk(root, [])
    return found


def _ordered(root: int, steps: list[Step]) -> list[Step]:
    """Distinct steps in an order where each starts at a table already joined."""
    unique = list({(step.edge.id, step.forward): step for step in steps}.values())
    joined, ordered = {root}, []
    while unique:
        ready = [step for step in unique if step.start in joined and step.end not in joined]
        if not ready:
            break
        for step in ready:
            if step.end not in joined:
                ordered.append(step)
                joined.add(step.end)
        unique = [step for step in unique if step.end not in joined]
    return ordered


def shortest_path_tree(graph: SchemaGraph, root: int, terminals: list[int]) -> JoinTree | None:
    """The union of Dijkstra's paths from the root along steps that repeat no row; None if some table is unreachable."""
    cost, reached_by, paths = _shortest_paths(graph, root, allow_fanout=False)
    targets = [table for table in dict.fromkeys(terminals) if table != root]
    if any(table not in cost for table in targets):
        return None
    steps = [step for table in targets for step in _path_to(reached_by, root, table)]
    alternatives = {
        table: _alternatives(graph, root, table, cost, allow_fanout=False)
        for table in targets if paths[table] > 1
    }
    for table, options in alternatives.items():
        chosen = [step.edge.id for step in _path_to(reached_by, root, table)]
        options.sort(key=lambda option: option != chosen)
    return JoinTree(root, _ordered(root, steps), "dijkstra", alternatives)


def steiner_tree(graph: SchemaGraph, root: int, terminals: list[int]) -> JoinTree:
    """A directed Steiner tree from the root over every step, fan-out ones included. Raises NoJoinPath."""
    targets = [table for table in dict.fromkeys(terminals) if table != root]
    tables = sorted(graph.tables)
    searches = {table: _shortest_paths(graph, table, allow_fanout=True) for table in tables}
    unreachable = [table for table in targets if table not in searches[root][0]]
    if unreachable:
        raise NoJoinPath(unreachable)
    if not targets:
        return JoinTree(root, [], "steiner")

    def distance(start: int, end: int) -> float:
        return searches[start][0].get(end, INFINITY)

    def path(start: int, end: int) -> list[Step]:
        return _path_to(searches[start][1], start, end)

    if len(targets) > EXACT_TERMINALS:
        return JoinTree(root, _ordered(root, _takahashi_matsuyama(root, targets, distance, path)), "steiner_heuristic")
    return JoinTree(root, _ordered(root, _dreyfus_wagner(root, targets, tables, distance, path)), "steiner")


def _dreyfus_wagner(root, targets, tables, distance, path) -> list[Step]:
    """Exact: `best[mask][v]` is the cheapest tree rooted at `v` reaching the targets in `mask`."""
    full = (1 << len(targets)) - 1
    best: dict[int, dict[int, float]] = {}
    split: dict[int, dict[int, int | None]] = {}
    move: dict[int, dict[int, int]] = {}
    for mask in range(1, full + 1):
        merged, merged_split = {}, {}
        for table in tables:
            if mask & (mask - 1) == 0:
                merged[table] = distance(table, targets[mask.bit_length() - 1])
                merged_split[table] = None
                continue
            merged[table], merged_split[table] = INFINITY, None
            sub = (mask - 1) & mask
            while sub:
                candidate = best[sub][table] + best[mask ^ sub][table]
                if candidate < merged[table]:
                    merged[table], merged_split[table] = candidate, sub
                sub = (sub - 1) & mask
        best[mask], split[mask], move[mask] = {}, merged_split, {}
        for table in tables:
            options = [(distance(table, other) + merged[other], other) for other in tables]
            best[mask][table], move[mask][table] = min(options, key=lambda option: (option[0], option[1] != table))

    steps: list[Step] = []

    def build(mask: int, table: int) -> None:
        branch = move[mask][table]
        if branch != table:
            steps.extend(path(table, branch))
        if split[mask][branch] is None:
            steps.extend(path(branch, targets[mask.bit_length() - 1]))
        else:
            build(split[mask][branch], branch)
            build(mask ^ split[mask][branch], branch)

    build(full, root)
    return steps


def _takahashi_matsuyama(root, targets, distance, path) -> list[Step]:
    """Heuristic: grow the tree by the cheapest path from any table in it to a target not reached yet."""
    in_tree, remaining, steps = {root}, set(targets), []
    while remaining:
        _cost, start, target = min((distance(start, target), start, target) for start in in_tree for target in remaining)
        new_steps = path(start, target)
        steps.extend(new_steps)
        in_tree.update(step.end for step in new_steps)
        remaining -= in_tree
    return steps


def join_tree(graph: SchemaGraph, root: int, terminals: list[int]) -> JoinTree:
    """Dijkstra from the root when it reaches every table without repeating rows, a Steiner tree otherwise."""
    return shortest_path_tree(graph, root, terminals) or steiner_tree(graph, root, terminals)
