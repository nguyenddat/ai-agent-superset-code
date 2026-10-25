from dataclasses import dataclass

from text_to_bi.superset_semantic_layer.modules.business_model.lineage_overrides import flipped_key, match_override


@dataclass
class Row:
    is_hidden: bool = False
    is_manual: bool = False


def test_flip_swaps_direction_and_kind_and_is_its_own_inverse():
    assert flipped_key((1, 2, "flow")) == (2, 1, "relation")
    assert flipped_key((2, 1, "relation")) == (1, 2, "flow")
    assert flipped_key(flipped_key((1, 2, "flow"))) == (1, 2, "flow")


def test_exact_key_wins():
    row = Row(is_hidden=True)
    assert match_override((1, 2, "flow"), {(1, 2, "flow")}, {(1, 2, "flow"): row}) is row


def test_hidden_row_follows_the_edge_when_its_kind_flips():
    # Hidden while FK was a relation 2 -> 1; layers moved, so the edge is now a flow 1 -> 2.
    row = Row(is_hidden=True)
    assert match_override((1, 2, "flow"), {(1, 2, "flow")}, {(2, 1, "relation"): row}) is row


def test_colour_only_row_follows_the_edge_when_its_kind_flips():
    row = Row(is_manual=False)
    assert match_override((2, 1, "relation"), {(2, 1, "relation")}, {(1, 2, "flow"): row}) is row


def test_manual_edge_is_not_remapped():
    row = Row(is_manual=True)
    assert match_override((1, 2, "flow"), {(1, 2, "flow")}, {(2, 1, "relation"): row}) is None


def test_row_belonging_to_another_inferred_edge_is_not_taken():
    row = Row(is_hidden=True)
    inferred = {(1, 2, "flow"), (2, 1, "relation")}
    assert match_override((1, 2, "flow"), inferred, {(2, 1, "relation"): row}) is None


def test_no_row_means_no_override():
    assert match_override((1, 2, "flow"), {(1, 2, "flow")}, {}) is None
