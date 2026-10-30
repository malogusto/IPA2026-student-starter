"""Shared helpers for backend adapters."""

import os
import socket
from ipaddress import IPv4Interface, IPv4Network


def ok(result, **extra):
    return {"status": "ok", "result": result, **extra}


def error(result):
    return {"status": "error", "result": result}


def not_found():
    return ok("not_found", interface=None)


def router_credentials():
    return os.environ.get("ROUTER_USER", ""), os.environ.get("ROUTER_PASS", "")


def error_from_exception(exc):
    """Map built-in exception categories to the common error codes."""
    if isinstance(exc, PermissionError):
        return error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout, socket.gaierror)):
        return error("connection_failed")
    return error("backend_failed")


def loopback_number(interface_name):
    """Loopback123 -> "123"."""
    prefix = "Loopback"
    if not interface_name.startswith(prefix) or not interface_name[len(prefix):].isdigit():
        raise ValueError(f"not a Loopback interface: {interface_name}")
    return interface_name[len(prefix):]


def split_ipv4(cidr):
    """172.23.123.1/32 -> ("172.23.123.1", "255.255.255.255")."""
    interface = IPv4Interface(cidr)
    return str(interface.ip), str(interface.network.netmask)


def to_cidr(ip, netmask_or_prefix):
    prefix = IPv4Network(f"0.0.0.0/{netmask_or_prefix}").prefixlen
    return f"{ip}/{prefix}"
