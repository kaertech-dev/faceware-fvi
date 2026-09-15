from datetime import datetime
from app.db import query_all, query_one, get_conn

REQUIRED_STATIONS = ("assembly1", "soldering2", "assembly2", "vi2", "assembly4", "finaltest", "lasermarking1", "packing",)
MAX_FAIL_COUNT = 3

def lookup_unit(serial_num: str):
    """Check b2btag_main for the serial and its station statuses."""
    return query_one(
        """
        SELECT serial_num, po_num, assembly1, soldering2, assembly2, vi2, assembly4, finaltest, lasermarking1, packing
        FROM ledtech.faceware_main
        WHERE serial_num = %s
        LIMIT 1
        """,
        (serial_num,)
    )

def already_packed(serial_num: str) -> bool:
    row = query_one(
        "SELECT serial_num FROM ledtech.faceware_fvi WHERE serial_num = %s LIMIT 1",
        (serial_num,)
    )
    return row is not None

def stations_passed(row: dict) -> bool:
    """Return True if all required stations are recorded as 1."""
    return all(row.get(s) == 1 for s in REQUIRED_STATIONS)

def failure_count(serial_num: str) -> int:
    """Return the highest recorded failed-attempt number for a unit."""
    rows = query_all(
        """
        SELECT serial_num
        FROM ledtech.faceware_fvi
        WHERE LEFT(serial_num, CHAR_LENGTH(%s)) = %s AND status = 0
        """,
        (serial_num, serial_num),
    )

    attempt_numbers = []
    prefix = f"{serial_num}_"
    for row in rows:
        suffix = row["serial_num"][len(prefix):]
        if suffix.isdigit():
            attempt_numbers.append(int(suffix))
    return max(attempt_numbers, default=0)


def record_packing(serial_num: str, po_num: str, operator_en: str, shift: str, test_rep: int, remarks: str = ""):
    """
    Atomically:
      1. Set vi=1 in ledtech.faceware_main
    2. Insert a row into ledtech.faceware_fvi (status=1)
    Used for PASS.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE ledtech.faceware_main
            SET fvi = 1, lasermarking2 = 1
            WHERE serial_num = %s
            """,
            (serial_num,)
        )

        cur.execute(
            """
            INSERT INTO ledtech.faceware_fvi
                (serial_num, po_num, operator_en, shift, date_time, test_rep, remarks, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (serial_num, po_num, operator_en, shift, datetime.now(), test_rep, remarks)
        )

        cur.execute(
            """
            INSERT INTO ledtech.faceware_lasermarking2
                (serial_num, po_num, operator_en, shift, date_time, test_rep, remarks, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (serial_num, po_num, operator_en, shift, datetime.now(), test_rep, remarks)
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def record_fail(serial_num: str, po_num: str, operator_en: str, shift: str, reason: str):
    """
    Record a FAIL:
    - Inserts into both tables with serial_num suffixed by the next attempt number
      - status = 0, remarks = reason
      - ledtech.faceware_main.fvi is NOT touched (unit isn't considered packed,
        so it can be reworked and re-scanned under its original serial).
    """
    previous_failures = failure_count(serial_num)
    if previous_failures >= MAX_FAIL_COUNT:
        raise ValueError(f"Serial '{serial_num}' reached the maximum of {MAX_FAIL_COUNT} failed attempts. Endorsed that to FA, Thank you")

    test_rep = previous_failures + 1
    fail_serial = f"{serial_num}_{test_rep}"
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ledtech.faceware_fvi
                (serial_num, po_num, operator_en, shift, date_time, test_rep, remarks, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            """,
            (fail_serial, po_num, operator_en, shift, datetime.now(), test_rep, reason)
        )
        cur.execute(
            """
            INSERT INTO ledtech.faceware_lasermarking2
                (serial_num, po_num, operator_en, shift, date_time, test_rep, remarks, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            """,
            (fail_serial, po_num, operator_en, shift, datetime.now(), test_rep, reason)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"fail_serial": fail_serial, "test_rep": test_rep}

def validate_scan(serial_num: str):
    """
    Step 2: validate serial against prog_id, stations, already-packed.
    Does NOT record anything — just tells the UI whether it's OK to
    show the PASS / FAIL buttons.
    Returns:
      status : "ok" | "already_packed" | "fail" | "not_found" | "mismatch"
      message: human-readable string
      unit   : the faceware_main row (or None)
    """
    serial_num = serial_num.strip()

    unit = lookup_unit(serial_num)
    if not unit:
        return {"status": "not_found", "message": f"Serial '{serial_num}' not found in database.", "unit": None}

    if already_packed(serial_num):
        return {"status": "already_packed", "message": f"Serial '{serial_num}' was already packed.", "unit": unit}

    if not stations_passed(unit):
        failed = [s for s in REQUIRED_STATIONS if unit.get(s) != 1]
        return {
            "status": "fail",
            "message": f"Serial '{serial_num}' has not passed: {', '.join(failed).upper()}.",
            "unit": unit,
        }

    # if not verify_prog_matches_serial(prog_id, serial_num):
    #     return {
    #         "status": "mismatch",
    #         "message": f"Prog ID '{prog_id}' does not match serial '{serial_num}'.",
    #         "unit": unit,
    #     }

    return {
        "status": "ok",
        "message": f"Serial '{serial_num}' verified. Choose PASS or FAIL.",
        "unit": unit,
    }

def finalize_scan(serial_num: str, operator_en: str, shift: str, decision: str, remarks: str = ""):
    """
    Step 3: record the operator's decision.
    Re-runs validate_scan first so a stale/tampered client can't force a write.
    decision: "pass" | "fail"
    """
    serial_num = serial_num.strip()
    decision = (decision or "").strip().lower()

    if decision not in ("pass", "fail"):
        return {"status": "fail", "message": "Invalid decision.", "unit": None}

    check = validate_scan(serial_num)#prog_id, 
    if check["status"] != "ok":
        return check

    unit = check["unit"]

    if decision == "fail":
        reason = remarks.strip()
        if not reason:
            return {"status": "fail", "message": "A fail reason is required.", "unit": unit}
        previous_failures = failure_count(serial_num)
        if previous_failures >= MAX_FAIL_COUNT:
            return {
                "status": "fail",
                "message": f"Serial '{serial_num}' reached the maximum of {MAX_FAIL_COUNT} failed attempts.",
                "unit": unit,
            }
        failure = record_fail(serial_num, unit["po_num"], operator_en, shift, reason)
        return {
            "status": "ok",
            "message": f"Serial '{serial_num}' recorded as FAIL: {reason}",
            "unit": unit,
            "decision": "fail",
            **failure,
        }

    test_rep = max(failure_count(serial_num), 1)
    record_packing(serial_num, unit["po_num"], operator_en, shift, test_rep, remarks)
    return {
        "status": "ok",
        "message": f"Serial '{serial_num}' packed successfully.",
        "unit": unit,
        "decision": "pass",
    }