import re

CANVAS_DOMAIN_KEY = re.compile(r"^domain-(\d+|unassigned)$")

CANVAS_MAX_CELLS = 20_000

CANVAS_MAX_COORDINATE = 100_000

LINEAGE_NODE_KEY = re.compile(r"^(table|metric)-\d+$")

LINEAGE_EDGE_KEY = re.compile(r"^((flow|relation)-\d+-\d+|metric-edge-\d+)$")

LINEAGE_EDGE_STYLES = {"orthogonal", "straight", "curved"}

LINEAGE_MAX_ITEMS = 5_000

LINEAGE_MAX_POINTS = 50
