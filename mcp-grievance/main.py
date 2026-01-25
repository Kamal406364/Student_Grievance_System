from mcp.server.fastmcp import FastMCP
from db import get_db_connection
import sys
from pathlib import Path

# Add parent directory to path to import shared functions
parent_path = Path(__file__).parent.parent
sys.path.insert(0, str(parent_path))

app = FastMCP("mcp-grievance")


# ============================
# 1) TOOL: Route Ticket (AI)
# ============================
@app.tool()
def route_ticket_tool(description: str) -> dict:
    """
    AI tool: Classify the complaint into service department + priority.
    NOTE: For now it's rule-based.
    """
    return route_ticket(description)


# ============================
# 2) TOOL: Create Ticket
# ============================
@app.tool()
def create_ticket_tool(student_id: int, description: str) -> dict:
    """
    Student creates a ticket.
    - Finds student's academic dept
    - Finds HOD for that dept
    - Routes complaint to service dept
    - Inserts ticket + hod approval + ticket update history
    """
    return create_ticket(student_id, description)


# ============================
# 3) TOOL: HOD Decision
# ============================
@app.tool()
def hod_decision_tool(ticket_id: int, hod_id: int, decision: str, remarks: str = None) -> dict:
    """
    HOD approves/rejects ticket.
    If APPROVED -> auto assign to service department INCHARGE
    """
    return hod_decision(ticket_id, hod_id, decision, remarks)
    """
    HOD approves/rejects ticket.
    If APPROVED -> auto assign to service department INCHARGE
    """
    decision = decision.upper().strip()

    # input allowed from user
    decision_map = {
        "APPROVED": "HOD_APPROVED",
        "REJECTED": "HOD_REJECTED"
    }

    if decision not in decision_map:
        return {"error": "decision must be APPROVED or REJECTED"}

    db_decision = decision_map[decision]  # HOD_APPROVED / HOD_REJECTED

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1) Validate ticket belongs to hod
            cur.execute("""
                SELECT hod_id, target_service_dept_id
                FROM tickets
                WHERE ticket_id=%s
            """, (ticket_id,))
            t = cur.fetchone()

            if not t:
                return {"error": "Ticket not found"}

            if t["hod_id"] != hod_id:
                return {"error": "This ticket does not belong to this HOD"}

            # 2) Update hod approval table (decision is HOD_APPROVED / HOD_REJECTED)
            cur.execute("""
                UPDATE hod_approvals
                SET decision=%s, remarks=%s, approved_at=NOW()
                WHERE ticket_id=%s AND hod_id=%s
            """, (db_decision, remarks, ticket_id, hod_id))

            # 3) If rejected -> update ticket and stop
            if db_decision == "HOD_REJECTED":
                cur.execute("""
                    UPDATE tickets
                    SET status='HOD_REJECTED'
                    WHERE ticket_id=%s
                """, (ticket_id,))

                cur.execute("""
                    INSERT INTO ticket_updates(ticket_id, updated_by, message, status)
                    VALUES (%s,%s,%s,'HOD_REJECTED')
                """, (ticket_id, hod_id, "HOD rejected the ticket"))

                conn.commit()
                return {"ticket_id": ticket_id, "status": "HOD_REJECTED", "decision": db_decision}

            # 4) Approved -> find service dept incharge
            service_dept_id = t["target_service_dept_id"]

            cur.execute("""
                SELECT user_id
                FROM users
                WHERE role='INCHARGE' AND service_dept_id=%s
                LIMIT 1
            """, (service_dept_id,))
            incharge = cur.fetchone()

            # If no incharge exists, still mark HOD_APPROVED (do not fail with wrong status)
            if not incharge:
                cur.execute("""
                    UPDATE tickets
                    SET status='HOD_APPROVED'
                    WHERE ticket_id=%s
                """, (ticket_id,))

                cur.execute("""
                    INSERT INTO ticket_updates(ticket_id, updated_by, message, status)
                    VALUES (%s,%s,%s,'HOD_APPROVED')
                """, (ticket_id, hod_id, "HOD approved, but no incharge found for service department"))

                conn.commit()
                return {"error": "No incharge found for this service department", "ticket_id": ticket_id, "status": "HOD_APPROVED"}

            incharge_id = incharge["user_id"]

            # 5) Assign ticket to incharge + update status
            cur.execute("""
                UPDATE tickets
                SET status='ASSIGNED_TO_INCHARGE',
                    assigned_incharge_id=%s
                WHERE ticket_id=%s
            """, (incharge_id, ticket_id))

            # 6) Insert update history
            cur.execute("""
                INSERT INTO ticket_updates(ticket_id, updated_by, message, status)
                VALUES (%s,%s,%s,'ASSIGNED_TO_DEPT')
            """, (ticket_id, hod_id, f"HOD approved. Assigned to incharge_id={incharge_id}"))


            conn.commit()

            return {
                "ticket_id": ticket_id,
                "decision": db_decision,
                "status": "ASSIGNED_TO_INCHARGE",
                "assigned_incharge_id": incharge_id
            }

    finally:
        conn.close()


# ============================
# 4) TOOL: Incharge Update Status
# ============================
@app.tool()
def update_ticket_status(ticket_id: int, incharge_id: int, status: str, message: str = None) -> dict:
    """
    Incharge updates ticket progress.
    Allowed statuses: IN_PROGRESS, RESOLVED, CLOSED
    """
    status = status.upper().strip()

    allowed = {"IN_PROGRESS", "RESOLVED", "CLOSED"}
    if status not in allowed:
        return {"error": f"status must be one of {sorted(list(allowed))}"}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check ticket belongs to this incharge
            cur.execute("""
                SELECT assigned_incharge_id, status
                FROM tickets
                WHERE ticket_id=%s
            """, (ticket_id,))
            t = cur.fetchone()

            if not t:
                return {"error": "Ticket not found"}

            if t["assigned_incharge_id"] != incharge_id:
                return {"error": "This ticket is not assigned to this incharge"}

            # Update ticket
            cur.execute("""
                UPDATE tickets
                SET status=%s
                WHERE ticket_id=%s
            """, (status, ticket_id))

            # Update history
            cur.execute("""
                INSERT INTO ticket_updates(ticket_id, updated_by, message, status)
                VALUES (%s,%s,%s,%s)
            """, (ticket_id, incharge_id, message or f"Status updated to {status}", status))

            conn.commit()

            return {"ticket_id": ticket_id, "status": status, "message": message}

    finally:
        conn.close()
