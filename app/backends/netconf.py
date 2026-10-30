import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

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

IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"
NETCONF_PORT = 830
TIMEOUT = 10


def _connect(router):
    from ncclient import manager

    username, password = router_credentials()
    return manager.connect(
        host=router,
        port=NETCONF_PORT,
        username=username,
        password=password,
        hostkey_verify=False,
        allow_agent=False,
        look_for_keys=False,
        device_params={"name": "iosxe"},
        timeout=TIMEOUT,
    )


def _default_get_config(router, filter_xml):
    with _connect(router) as m:
        reply = m.get_config(source="running", filter=("subtree", filter_xml))
        return reply.xml


def _default_edit_config(router, config_xml):
    with _connect(router) as m:
        m.edit_config(target="running", config=config_xml)


def _error_from_exception(exc):
    try:
        from ncclient.operations.errors import TimeoutExpiredError
        from ncclient.operations.rpc import RPCError
        from ncclient.transport.errors import (
            AuthenticationError,
            SSHError,
            TransportError,
        )
    except ImportError:
        return error_from_exception(exc)

    if isinstance(exc, AuthenticationError):
        return error("authentication_failed")
    if isinstance(exc, (SSHError, TransportError, TimeoutExpiredError)):
        return error("connection_failed")
    if isinstance(exc, RPCError):
        return error("backend_failed")
    return error_from_exception(exc)


def build_status_filter(interface_name):
    return (
        f'<interfaces xmlns="{IF_NS}">'
        f"<interface><name>{escape(interface_name)}</name></interface>"
        f"</interfaces>"
    )


def _text(element, path):
    found = element.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def parse_interface(xml_text, interface_name):
    root = ET.fromstring(xml_text)

    for interface in root.iter(f"{{{IF_NS}}}interface"):
        if _text(interface, f"{{{IF_NS}}}name") != interface_name:
            continue

        ipv4 = None
        address = interface.find(f"{{{IP_NS}}}ipv4/{{{IP_NS}}}address")
        if address is not None:
            ip = _text(address, f"{{{IP_NS}}}ip")
            netmask = _text(address, f"{{{IP_NS}}}netmask")
            if ip and netmask:
                ipv4 = to_cidr(ip, netmask)

        enabled = _text(interface, f"{{{IF_NS}}}enabled")

        return {
            "name": interface_name,
            "ipv4": ipv4,
            "description": _text(interface, f"{{{IF_NS}}}description"),
            "admin_state": "down" if enabled == "false" else "up",
        }

    return None


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    netconf_get_config = netconf_get_config or _default_get_config

    try:
        xml_text = netconf_get_config(router, build_status_filter(interface_name))
    except Exception as exc:
        return _error_from_exception(exc)

    try:
        interface = parse_interface(xml_text, interface_name)
    except Exception:
        return error("backend_failed")

    if interface is None:
        return not_found()
    return ok("found", interface=interface)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config),
    )


def build_native_config(desired_interface):
    number = loopback_number(desired_interface["name"])
    address, mask = split_ipv4(desired_interface["ipv4"])
    shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""

    return (
        '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" '
        'xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
        '<native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">'
        "<interface>"
        '<Loopback nc:operation="replace">'
        f"<name>{number}</name>"
        f"<description>{escape(str(desired_interface['description']))}</description>"
        "<ip><address><primary>"
        f"<address>{address}</address>"
        f"<mask>{mask}</mask>"
        "</primary></address></ip>"
        f"{shutdown}"
        "</Loopback>"
        "</interface>"
        "</native>"
        "</config>"
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    netconf_edit_config = netconf_edit_config or _default_edit_config

    try:
        config_xml = build_native_config(desired_interface)
    except (KeyError, ValueError):
        return error("backend_failed")

    try:
        netconf_edit_config(router, config_xml)
    except Exception as exc:
        return _error_from_exception(exc)

    return ok("applied")
