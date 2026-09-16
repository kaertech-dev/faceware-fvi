from app.db import query_one

def authenticate_operator(employee_num: str):
    """
    Look up employee_num in operators.main under operator_en column.
    Returns operator dict or None.
    """
    row = query_one(
        "SELECT operator_en, employee_name FROM operators.main WHERE operator_en = %s LIMIT 1",
        (employee_num,)
    )
    return row
