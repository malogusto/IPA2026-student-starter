import yaml


ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

CAPABILITIES = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}

ADMIN_STATES = {"up", "down"}


def error(result):
    return {"status": "error", "result": result}


def _is_missing(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    if not isinstance(data, dict):
        return error("invalid_yaml")

    # YAML integer 1 only: bool is a subclass of int, so exclude it.
    version = data.get("version")
    if type(version) is not int or version != 1:
        return error("invalid_version")

    router = data.get("router")
    if _is_missing(router):
        return error("missing_router")
    if not isinstance(router, str) or router not in ALLOWED_ROUTERS:
        return error("invalid_router")

    method = data.get("method")
    if _is_missing(method):
        return error("missing_method")
    if not isinstance(method, str) or method not in CAPABILITIES:
        return error("invalid_method")

    action = data.get("action")
    if _is_missing(action):
        return error("missing_action")
    if not isinstance(action, str) or action not in CAPABILITIES[method]:
        return error("invalid_action")

    desired = data.get("desired")
    if not isinstance(desired, dict):
        return error("missing_desired")

    interface = desired.get("interface")
    if not isinstance(interface, dict):
        return error("missing_interface")

    if _is_missing(interface.get("name")):
        return error("missing_interface_name")

    if action in ("plan", "apply"):
        if _is_missing(interface.get("ipv4")):
            return error("missing_ipv4")
        if _is_missing(interface.get("description")):
            return error("missing_description")
        admin_state = interface.get("admin_state")
        if _is_missing(admin_state):
            return error("missing_admin_state")
        if admin_state not in ADMIN_STATES:
            return error("invalid_admin_state")

    return {"status": "ok", "result": "accepted"}


def load_request_file(path):
    """
    Parse a YAML request file.

    Return (data, None) on success, or (None, error_response).
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return None, error("invalid_yaml")

    if not isinstance(data, dict):
        return None, error("invalid_yaml")

    return data, None


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    data, load_error = load_request_file(path)
    if load_error is not None:
        return load_error

    return validate_request(data)
