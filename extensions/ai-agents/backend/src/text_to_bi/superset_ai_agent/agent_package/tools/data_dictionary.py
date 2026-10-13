from typing import Any

from langchain.tools import ToolRuntime, tool


def _optional_dictionary_columns(dataset_ids: list[int], allowed_dataset_ids: list[int]) -> dict[str, Any]:
    """Read optional Semantic Layer tables without importing that extension."""
    from sqlalchemy import bindparam, inspect, text
    from superset.extensions import db

    dataset_table = "text_to_bi_dataset_dictionary"
    column_table = "text_to_bi_column_dictionary"
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table(dataset_table) or not inspector.has_table(column_table):
            return {
                "available": False,
                "reason": "Data Dictionary chưa được cài đặt hoặc chưa khởi tạo.",
                "datasets": [],
            }

        dataset_columns = {column["name"] for column in inspector.get_columns(dataset_table)}
        column_columns = {column["name"] for column in inspector.get_columns(column_table)}
        required_dataset_columns = {"id", "display_name"}
        required_column_columns = {"dataset_id", "column_name", "display_name", "data_type"}
        schema_is_compatible = (
            required_dataset_columns.issubset(dataset_columns)
            and required_column_columns.issubset(column_columns)
        )
        if not schema_is_compatible:
            return {
                "available": False,
                "reason": "Schema Data Dictionary không tương thích.",
                "datasets": [],
            }

        dataset_fields = {
            "description": "d.description",
            "grain": "d.grain",
            "dataset_type": "d.dataset_type",
        }
        column_fields = {
            "unit": "c.unit",
            "format": "c.format",
            "business_term": "c.business_term",
            "is_pk": "c.is_pk",
            "is_fk": "c.is_fk",
        }
        selections = ["d.id AS dataset_id", "d.display_name AS dataset_display_name"]
        selections.extend(
            f"{expression} AS {name}" if name in dataset_columns else f"NULL AS {name}"
            for name, expression in dataset_fields.items()
        )
        selections.extend([
            "c.column_name",
            "c.display_name AS column_display_name",
            "c.data_type",
        ])
        selections.extend(
            f"{expression} AS {name}" if name in column_columns else f"NULL AS {name}"
            for name, expression in column_fields.items()
        )

        has_reference = "referenced_column" in column_columns
        if has_reference:
            selections.extend([
                "referenced.dataset_id AS referenced_dataset_id",
                "referenced.column_name AS referenced_column_name",
                "target_dataset.display_name AS referenced_dataset_display_name",
            ])
            reference_joins = (
                "LEFT JOIN text_to_bi_column_dictionary AS referenced "
                "ON referenced.id = c.referenced_column "
                "LEFT JOIN text_to_bi_dataset_dictionary AS target_dataset "
                "ON target_dataset.id = referenced.dataset_id"
            )
        else:
            selections.extend([
                "NULL AS referenced_dataset_id",
                "NULL AS referenced_column_name",
                "NULL AS referenced_dataset_display_name",
            ])
            reference_joins = ""

        statement = text(
            "SELECT " + ", ".join(selections) +
            " FROM text_to_bi_dataset_dictionary AS d "
            "LEFT JOIN text_to_bi_column_dictionary AS c ON c.dataset_id = d.id "
            + reference_joins +
            " WHERE d.id IN :dataset_ids ORDER BY d.id, c.column_name"
        ).bindparams(bindparam("dataset_ids", expanding=True))
        rows = db.session.execute(statement, {"dataset_ids": dataset_ids}).mappings().all()
        datasets: dict[int, dict[str, Any]] = {}
        for row in rows:
            dataset = datasets.setdefault(row["dataset_id"], {
                "dataset_id": row["dataset_id"],
                "display_name": row["dataset_display_name"],
                "description": row["description"],
                "grain": row["grain"],
                "classification": row["dataset_type"],
                "columns": [],
            })
            if row["column_name"] is None:
                continue
            reference_is_allowed = row["referenced_dataset_id"] in allowed_dataset_ids
            dataset["columns"].append({
                "column_name": row["column_name"],
                "display_name": row["column_display_name"],
                "data_type": row["data_type"],
                "unit": row["unit"],
                "format": row["format"],
                "business_term": row["business_term"],
                "is_primary_key": row["is_pk"],
                "is_foreign_key": row["is_fk"],
                "referenced_dataset_id": row["referenced_dataset_id"] if reference_is_allowed else None,
                "referenced_dataset": row["referenced_dataset_display_name"] if reference_is_allowed else None,
                "referenced_column": row["referenced_column_name"] if reference_is_allowed else None,
            })
        return {"available": True, "datasets": list(datasets.values())}
    finally:
        db.session.remove()


@tool
def get_data_dictionary(runtime: ToolRuntime, dataset_id: int | None = None) -> dict[str, Any]:
    """Đọc định nghĩa nghiệp vụ tùy chọn của dataset và các cột trên dashboard.

    Dùng để hiểu tên hiển thị, business term, unit, grain, phân loại base/aggregate,
    khóa chính/ngoại và reference đã được người dùng khai báo. Kết quả chỉ là metadata,
    không chứa dữ liệu hàng. Nếu Data Dictionary chưa được cài, tool trả available=false;
    tiếp tục dùng các catalog Superset thông thường.
    """
    allowed_ids = [int(allowed_id) for allowed_id in runtime.context.get("allowed_dataset_ids", [])]
    requested_ids = allowed_ids
    if dataset_id is not None:
        if dataset_id not in allowed_ids:
            return {
                "error": f"Dataset ID {dataset_id} không thuộc dashboard hiện tại.",
                "allowed_dataset_ids": allowed_ids,
            }
        requested_ids = [dataset_id]
    if not requested_ids:
        return {"available": True, "datasets": []}
    try:
        return _optional_dictionary_columns(requested_ids, allowed_ids)
    except Exception:
        return {
            "available": False,
            "reason": "Không đọc được Data Dictionary tùy chọn.",
            "datasets": [],
        }
