import re

from app.backends.common import (
    error,
    error_from_exception,
    not_found,
    ok,
    router_credentials,
)

TIMEOUT = 10

# IOS abbreviations seen in "show interfaces description".
INTERFACE_TYPES = (
    "Loopback",
    "GigabitEthernet",
    "TenGigabitEthernet",
    "FastEthernet",
    "Ethernet",
    "Vlan",
    "Tunnel",
    "Port-channel",
)


def normalize_interface_name(name):
    """Lo123 / lo123 / Loopback123 -> Loopback123."""
    if not name:
        return name
    match = re.match(r"^([A-Za-z\-]+)\s*(\d.*)$", name.strip())
    if not match:
        return name.strip()
    prefix, number = match.groups()
    for full in INTERFACE_TYPES:
        if len(prefix) >= 2 and full.lower().startswith(prefix.lower()):
            return f"{full}{number}"
    return f"{prefix}{number}"


def _connect(router):
    from netmiko import ConnectHandler

    username, password = router_credentials()
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=username,
        password=password,
        timeout=TIMEOUT,
        conn_timeout=TIMEOUT,
        auth_timeout=TIMEOUT,
    )


def _parsed(connection, command):
    output = connection.send_command(command, use_textfsm=True)
    if isinstance(output, list):
        return output
    # Unparsed text: an absent interface yields an IOS error message.
    text = output.lower()
    if "invalid input" in text or "not found" in text or not text.strip():
        return []
    raise RuntimeError(f"TextFSM could not parse: {command}")


def _read(connection, interface_name):
    ip_info = _parsed(connection, f"show ip interface {interface_name}")
    descriptions = _parsed(connection, "show interfaces description")
    return ip_info, descriptions


def _default_netmiko_get(router, interface_name):
    with _connect(router) as connection:
        return _read(connection, interface_name)


def _default_netmiko_delete(router, interface_name):
    with _connect(router) as connection:
        if normalize_state(interface_name, *_read(connection, interface_name)) is None:
            return "not_found"

        connection.send_config_set([f"no interface {interface_name}"])

        if normalize_state(interface_name, *_read(connection, interface_name)) is not None:
            raise RuntimeError(f"{interface_name} still present after delete")
        return "deleted"


def _error_from_exception(exc):
    try:
        from netmiko.exceptions import (
            NetmikoAuthenticationException,
            NetmikoTimeoutException,
        )
        from paramiko.ssh_exception import (
            AuthenticationException,
            NoValidConnectionsError,
            SSHException,
        )
    except ImportError:
        return error_from_exception(exc)

    if isinstance(exc, (NetmikoAuthenticationException, AuthenticationException)):
        return error("authentication_failed")
    if isinstance(exc, (NetmikoTimeoutException, NoValidConnectionsError, SSHException)):
        return error("connection_failed")
    return error_from_exception(exc)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return list(value)


def normalize_state(interface_name, ip_info, descriptions):
    record = None
    for item in ip_info or []:
        if normalize_interface_name(item.get("interface")) == interface_name:
            record = item
            break
    if record is None:
        return None

    ipv4 = None
    addresses = _as_list(record.get("ip_address"))
    prefixes = _as_list(record.get("prefix_length"))
    if addresses and prefixes:
        ipv4 = f"{addresses[0]}/{prefixes[0]}"

    description = None
    for item in descriptions or []:
        if normalize_interface_name(item.get("port")) == interface_name:
            description = item.get("description") or None
            break

    link_status = (record.get("link_status") or "").lower()

    return {
        "name": interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": "down" if "administratively down" in link_status else "up",
    }


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    netmiko_get = netmiko_get or _default_netmiko_get

    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
        interface = normalize_state(interface_name, ip_info, descriptions)
    except Exception as exc:
        return _error_from_exception(exc)

    if interface is None:
        return not_found()
    return ok("found", interface=interface)


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    netmiko_delete = netmiko_delete or _default_netmiko_delete

    try:
        result = netmiko_delete(router, interface_name)
    except Exception as exc:
        return _error_from_exception(exc)

    if result == "deleted":
        return ok("deleted")
    if result == "not_found":
        return not_found()
    return error("backend_failed")
