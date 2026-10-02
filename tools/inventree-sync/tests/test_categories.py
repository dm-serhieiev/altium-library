import pytest

from inventree_sync.categories import CategoryError, build_category_tree, group_parts, validate_export_names, validate_part_placement, validate_table_name
from inventree_sync.models import Category, Part


@pytest.fixture
def tree():
    return build_category_tree([
        Category(1, "Components", None), Category(2, "Passives", 1),
        Category(3, "Resistors", 2), Category(4, "Empty Leaf", 2),
        Category(5, "Outside", None),
    ])


def test_tree_and_scope(tree):
    assert tree.is_leaf(3)
    assert tree.is_leaf(4)
    assert not tree.is_leaf(1)
    assert not tree.is_leaf(2)
    assert tree.full_path(3) == "Components / Passives / Resistors"
    assert tree.resolve_path(("Components", "Passives")) == 2
    assert tree.subtree(2) == frozenset({2, 3, 4})
    with pytest.raises(TypeError):
        tree.categories[10] = Category(10, "Other", None)


def test_missing_parent():
    with pytest.raises(CategoryError, match="pk=2.*missing parent pk=9"):
        build_category_tree([Category(2, "Child", 9)])


@pytest.mark.parametrize("nodes", [[Category(1, "One", 1)], [Category(1, "One", 2), Category(2, "Two", 1)]])
def test_cycles(nodes):
    with pytest.raises(CategoryError, match="cycle"):
        build_category_tree(nodes)


def test_duplicate_pk():
    with pytest.raises(CategoryError, match="Duplicate category"):
        build_category_tree([Category(1, "One", None), Category(1, "Other", None)])


def test_deep_tree():
    tree = build_category_tree(Category(n, f"Level {n}", n - 1 if n > 1 else None) for n in range(1, 1100))
    assert len(tree.paths[1099]) == 1099


def test_ambiguous_scope():
    tree = build_category_tree([Category(1, "Root", None), Category(2, "Same", 1), Category(3, "Same", 1)])
    with pytest.raises(CategoryError, match="2 categories"):
        tree.resolve_path(("Root", "Same"))


def test_missing_scope(tree):
    with pytest.raises(CategoryError, match="0 categories"):
        tree.resolve_path(("Passives",))
    with pytest.raises(CategoryError, match="Unknown category"):
        tree.is_leaf(999)


def test_nonempty_leaves_only(tree):
    groups = group_parts([Part(20, "R-1", 3)], tree, 1)
    assert groups == {3: (Part(20, "R-1", 3),)}
    assert 4 not in groups


def test_empty_scope_is_error(tree):
    with pytest.raises(CategoryError, match="no exported Parts"):
        group_parts([], tree, 1)


@pytest.mark.parametrize("part,expected", [(Part(20, "R-1", 2), "non-leaf"), (Part(20, "R-1", None), "missing/unknown"), (Part(20, "R-1", 999), "missing/unknown"), (Part(20, None, 3), "IPN is required"), (Part(20, "", 3), "IPN is required"), (Part(20, "  ", 3), "IPN is required"), (Part(20, "R-1", 5), "outside")])
def test_invalid_part_placement(tree, part, expected):
    with pytest.raises(CategoryError, match=expected) as error:
        validate_part_placement(part, tree, tree.subtree(1))
    assert "Part pk=20" in str(error.value)
    assert "category pk=" in str(error.value)
    assert "path" in str(error.value)


@pytest.mark.parametrize("name", ["", " A", "A ", "A  B", "A/B", "A.B", "A_B", "A\nB", "1A", "АBC", "A" * 65, "MSysData", "usysData", "Select", "table", "Value", "GROUP BY", "LongChar", "CreateTableDef"])
def test_invalid_names(name):
    tree = build_category_tree([Category(1, "Root", None), Category(2, name, 1)])
    with pytest.raises(CategoryError) as error:
        validate_export_names(tree, [2])
    message = str(error.value)
    assert "pk=2" in message and "name=" in message and "path=" in message


@pytest.mark.parametrize("name", ["A", "A" * 64, "Fixed Resistors", "Current Sense and Shunt Resistors", "Aluminum Electrolytic Capacitors", "Select Parts"])
def test_valid_names(name):
    validate_table_name(name)


def test_duplicate_leaf_names_in_separate_branches():
    tree = build_category_tree([Category(1, "Root", None), Category(2, "Branch", 1), Category(3, "Parts", 1), Category(4, "parts", 2)])
    with pytest.raises(CategoryError, match="duplicate table name") as error:
        group_parts([Part(1, "ONE", 3), Part(2, "TWO", 4)], tree, 1)
    assert "pk=3" in str(error.value) and "pk=4" in str(error.value)
    # An empty duplicate-name leaf is not an export candidate.
    assert set(group_parts([Part(1, "ONE", 3)], tree, 1)) == {3}


def test_invalid_empty_leaf_is_ignored():
    tree = build_category_tree([Category(1, "Root", None), Category(2, "Bad/Name", 1), Category(3, "Parts", 1)])
    assert set(group_parts([Part(1, "ONE", 3)], tree, 1)) == {3}


@pytest.mark.parametrize("parts", [[Part(1, "ONE", 3), Part(1, "ONE", 3)], [Part(1, "ONE", 3), Part(2, "one", 3)]])
def test_duplicate_parts_and_ipns(tree, parts):
    with pytest.raises(CategoryError, match="[Dd]uplicate"):
        group_parts(parts, tree, 1)


def test_deterministic_tree_and_groups(tree):
    other = build_category_tree(reversed(list(tree.categories.values())))
    assert dict(other.paths) == dict(tree.paths)
    assert dict(other.children) == dict(tree.children)
    assert [p.pk for p in group_parts([Part(2, "TWO", 3), Part(1, "ONE", 3)], tree, 1)[3]] == [1, 2]

