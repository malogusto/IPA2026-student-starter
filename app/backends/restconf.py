import requests
import urllib3

from app.backends import planning
from app.backends.common import (
    error,
    error_from_exception,
    loopback_number,
    not_found,
    ok,
    router_credentials,
    split_ipv4,
    to_cidr,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "Accept": "application/yang-data+json",
    "Content-Type": "application/yang-data+json",
}
TIMEOUT = 10


def _status_url(router, interface_name):
    return (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )


def _native_url(router, number):
    return (
        f"https://{router}/restconf/data/"
        f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
    )


def _default_http_get(url):
    return requests.get(
        url,
        headers=HEADERS,
        auth=router_credentials(),
        verify=False,
        timeout=TIMEOUT,
    )


def _default_http_put(url, json):
    return requests.put(
        url,
        headers=HEADERS,
        json=json,
        auth=router_credentials(),
        verify=False,
        timeout=TIMEOUT,
    )


def _error_from_exception(exc):
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return error("connection_failed")
    return error_from_exception(exc)


def _normalize(raw, interface_name):
    data = raw.get("ietf-interfaces:interface")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        raise ValueError("malformed RESTCONF interface data")

    ipv4 = None
    addresses = (data.get("ietf-ip:ipv4") or {}).get("address") or []
    if addresses:
        ipv4 = to_cidr(addresses[0]["ip"], addresses[0]["netmask"])

    return {
        "name": data.get("name", interface_name),
        "ipv4": ipv4,
        "description": data.get("description"),
        "admin_state": "up" if data.get("enabled", True) else "down",
    }


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    http_get = http_get or _default_http_get

    try:
        response = http_get(_status_url(router, interface_name))
    except Exception as exc:
        return _error_from_exception(exc)

    if response.status_code == 404:
        return not_found()
    if response.status_code in (401, 403):
        return error("authentication_failed")
    if response.status_code != 200:
        return error("backend_failed")

    try:
        interface = _normalize(response.json(), interface_name)
    except Exception:
        return error("backend_failed")

    return ok("found", interface=interface)


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get),
    )


def build_native_payload(desired_interface):
    number = int(loopback_number(desired_interface["name"]))
    address, mask = split_ipv4(desired_interface["ipv4"])

    loopback = {
        "name": number,
        "description": desired_interface["description"],
        "ip": {
            "address": {
                "primary": {
                    "address": address,
                    "mask": mask,
                }
            }
        },
    }
    if desired_interface["admin_state"] == "down":
        loopback["shutdown"] = [None]

    return number, {"Cisco-IOS-XE-native:Loopback": loopback}


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    http_put = http_put or _default_http_put

    try:
        number, payload = build_native_payload(desired_interface)
    except (KeyError, ValueError):
        return error("backend_failed")

    try:
        response = http_put(_native_url(router, number), json=payload)
    except Exception as exc:
        return _error_from_exception(exc)

    if response.status_code in (200, 201, 204):
        return ok("applied")
    if response.status_code in (401, 403):
        return error("authentication_failed")
    return error("backend_failed")
