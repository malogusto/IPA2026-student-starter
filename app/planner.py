MANAGED_FIELDS = ("ipv4", "description", "admin_state")


def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    if current_interface is None:
        return {
            "status": "ok",
            "result": "planned",
            "operation": "create",
            "changes": {
                field: {"to": desired_interface.get(field)}
                for field in MANAGED_FIELDS
            },
        }

    changes = {}
    for field in MANAGED_FIELDS:
        desired_value = desired_interface.get(field)
        current_value = current_interface.get(field)
        if desired_value != current_value:
            changes[field] = {"from": current_value, "to": desired_value}

    return {
        "status": "ok",
        "result": "planned",
        "operation": "update" if changes else "no_change",
        "changes": changes,
    }
