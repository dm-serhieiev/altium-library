import pytest

from inventree_sync.models import ColumnDefinition, ModelRef, TECHNICAL_COLUMNS
from inventree_sync.validate import ExportValidationError, validate_model_uniqueness, validate_row


def test_separate_model_namespaces_and_same_library_reuse():
    seen = {}
    for ref in (
        ModelRef("symbol", "First.SchLib", "LED"),
        ModelRef("symbol", "First.SchLib", "LED"),
        ModelRef("footprint", "Second.PcbLib", "LED"),
    ):
        validate_model_uniqueness(ref, "Part pk=1", seen)
    assert len(seen) == 2


def test_global_model_comparison_is_case_insensitive():
    seen = {}
    validate_model_uniqueness(ModelRef("symbol", "First.SchLib", "OpAmp"), "Part pk=1", seen)
    validate_model_uniqueness(ModelRef("symbol", "FIRST.SchLib", "OpAmp"), "Part pk=2", seen)
    with pytest.raises(ExportValidationError, match="conflicts"):
        validate_model_uniqueness(ModelRef("symbol", "Other.SchLib", "OPAMP"), "Part pk=3", seen)


@pytest.mark.parametrize("defect", ["missing", "extra", "wrong_order", "number", "empty_technical", "null_technical"])
def test_complete_row_contract(defect):
    columns = TECHNICAL_COLUMNS + (ColumnDefinition("Value", 1),)
    row = {column.name: "example" for column in columns}
    if defect == "missing":
        del row["Value"]
    elif defect == "extra":
        row["Extra"] = "value"
    elif defect == "wrong_order":
        row = dict(reversed(tuple(row.items())))
    elif defect == "number":
        row["Value"] = 123
    elif defect == "empty_technical":
        row["IPN"] = " "
    else:
        row["Library Ref"] = None
    with pytest.raises(ExportValidationError, match="Part pk=1"):
        validate_row(row, columns, "Part pk=1")
