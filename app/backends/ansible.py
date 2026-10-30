import json
import os
import subprocess
from pathlib import Path

from app.backends.common import error, error_from_exception, ok, split_ipv4

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
PLAYBOOK = ANSIBLE_DIR / "apply_interface.yml"
INVENTORY = ANSIBLE_DIR / "inventory.ini"
TIMEOUT = 60

AUTH_MARKERS = (
    "authentication failed",
    "authentication error",
    "permission denied",
    "invalid credentials",
)
CONNECTION_MARKERS = (
    "unreachable",
    "timed out",
    "timeout",
    "unable to connect",
    "connection refused",
    "no route to host",
)


def _default_run_playbook(variables):
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(ANSIBLE_DIR / "ansible.cfg"),
        "ANSIBLE_HOST_KEY_CHECKING": "False",
    }
    try:
        completed = subprocess.run(
            [
                "ansible-playbook",
                "-i", str(INVENTORY),
                str(PLAYBOOK),
                "-e", json.dumps(variables),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError("ansible-playbook timed out") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ansible-playbook is not installed") from exc

    if completed.returncode == 0:
        return completed

    output = (completed.stdout + completed.stderr).lower()
    if any(marker in output for marker in AUTH_MARKERS):
        raise PermissionError(output[-500:])
    if any(marker in output for marker in CONNECTION_MARKERS):
        raise ConnectionError(output[-500:])
    raise RuntimeError(output[-500:])


def build_variables(router, desired_interface):
    address, netmask = split_ipv4(desired_interface["ipv4"])
    return {
        "router": router,
        "interface_name": desired_interface["name"],
        "description": desired_interface["description"],
        "ipv4_address": address,
        "netmask": netmask,
        "shutdown": desired_interface["admin_state"] == "down",
    }


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    run_playbook = run_playbook or _default_run_playbook

    try:
        variables = build_variables(router, desired_interface)
    except (KeyError, ValueError):
        return error("backend_failed")

    try:
        run_playbook(variables)
    except Exception as exc:
        return error_from_exception(exc)

    return ok("applied")
