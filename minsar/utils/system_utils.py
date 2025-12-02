#! /usr/bin/env python3
###############################################################################
#
# Project: System information and detection utilities
# Author: Falk Amelung
# Created: 2025
#
###############################################################################

import os
import sys
import platform
import socket
import subprocess
import shutil
import urllib.request
import json


def detect_operating_system():
    """Detect the operating system type.
    
    Returns:
        str: Operating system name ('macOS', 'Linux', 'Windows', or platform name)
    """
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    elif system == "Linux":
        return "Linux"
    elif system == "Windows":
        return "Windows"
    else:
        return system


def are_we_on_slurm_system():
    """Determine whether we are on a SLURM system.
    
    Returns:
        False: not a SLURM cluster (regular Linux, macOS, etc.)
        "compute_node": SLURM compute node
        "login_node": SLURM login or head/controller node
    """
    # No SLURM binaries → definitely not a SLURM system
    if not (shutil.which("sinfo") or shutil.which("scontrol")):
        return False

    # SLURMD_NODENAME is set only on compute nodes
    if "SLURMD_NODENAME" in os.environ:
        return "compute_node"

    # SLURM installed but not a compute node → login/head node
    return "login_node"


def get_system_name():
    """Get the system/hostname.
    
    Returns:
        str: Fully qualified hostname if available, otherwise simple hostname
    """
    try:
        # Try to get fully qualified domain name first
        hostname = subprocess.Popen(
            "hostname -f", 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        ).stdout.read().decode("utf-8").strip()
        if hostname:
            return hostname
    except:
        pass
    
    # Fallback to simple hostname
    try:
        hostname = socket.gethostname()
        return hostname
    except:
        return "unknown"


def get_public_IP():
    """Get the public IP address of the system by querying external services.
    
    This is useful when the system is behind NAT and you need the external/public IP.
    
    Returns:
        str: Public IP address, or None if unable to determine
    """
    services = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://ifconfig.me/ip", None),  # Returns plain text IP
        ("https://icanhazip.com", None),   # Returns plain text IP
        ("https://api.ip.sb/ip", None),    # Returns plain text IP
    ]
    
    for service_url, json_key in services:
        try:
            with urllib.request.urlopen(service_url, timeout=3) as response:
                if json_key:
                    data = json.loads(response.read().decode())
                    public_ip = data.get(json_key)
                else:
                    public_ip = response.read().decode().strip()
            if public_ip and public_ip:
                return public_ip
        except:
            continue
    
    return None


def get_ip_address():
    """Get the IP address of the system, preferring public/external IP.
    
    Priority order:
    1. SSH server IP (from SSH_CONNECTION environment variable)
    2. Public IP (from external service)
    3. Default route interface IP
    4. Socket connect method (fallback)
    
    Returns:
        str: IP address, or None if unable to determine
    """
    ip_addresses = {}
    
    # Method 1: Check SSH_CONNECTION (most reliable for SSH sessions)
    # SSH_CONNECTION format: "client_ip client_port server_ip server_port"
    ssh_conn = os.environ.get("SSH_CONNECTION")
    if ssh_conn:
        parts = ssh_conn.split()
        if len(parts) >= 3:
            server_ip = parts[2]  # The IP the SSH server is listening on
            ip_addresses["ssh_server"] = server_ip
    
    # Method 2: Get public IP from external service (if internet available)
    public_ip = get_public_IP()
    if public_ip:
        ip_addresses["public"] = public_ip
    
    # Method 3: Get IP from default route interface (Linux/Mac)
    try:
        if platform.system() == "Linux":
            # Get default route interface
            result = subprocess.run(
                ["ip", "route", "get", "8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Parse output like: "8.8.8.8 via 10.0.120.1 dev eth0 src 10.0.120.64"
                for line in result.stdout.split('\n'):
                    if 'src' in line:
                        parts = line.split()
                        src_idx = parts.index('src')
                        if src_idx + 1 < len(parts):
                            default_ip = parts[src_idx + 1]
                            ip_addresses["default_route"] = default_ip
        elif platform.system() == "Darwin":
            # macOS: get IP of default route interface
            result = subprocess.run(
                ["route", "get", "default"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                interface = None
                for line in result.stdout.split('\n'):
                    if 'interface:' in line:
                        interface = line.split(':')[1].strip()
                        break
                if interface:
                    result2 = subprocess.run(
                        ["ifconfig", interface],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result2.returncode == 0:
                        for line in result2.stdout.split('\n'):
                            if 'inet ' in line and '127.0.0.1' not in line:
                                ip = line.split()[1]
                                ip_addresses["default_route"] = ip
                                break
    except:
        pass
    
    # Method 4: Get IP by connecting to external address (fallback)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ip_addresses.values():
            ip_addresses["socket_connect"] = ip
    except:
        pass
    
    # Return priority: ssh_server > public > default_route > socket_connect
    for key in ["ssh_server", "public", "default_route", "socket_connect"]:
        if key in ip_addresses:
            return ip_addresses[key]
    
    # Last resort: try hostname resolution
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip != "127.0.0.1":
            return ip
    except:
        pass
    
    return None


def get_all_ip_addresses():
    """Get all IP addresses (useful for debugging).
    
    Returns:
        dict: Dictionary with different IP address types
    """
    all_ips = {}
    
    # SSH connection IP
    ssh_conn = os.environ.get("SSH_CONNECTION")
    if ssh_conn:
        parts = ssh_conn.split()
        if len(parts) >= 3:
            all_ips["ssh_server_ip"] = parts[2]
    
    # Public IP
    public_ip = get_public_IP()
    all_ips["public_ip"] = public_ip if public_ip else "unavailable"
    
    # All interface IPs (Linux)
    if platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                all_ips["all_interface_ips"] = result.stdout.strip().split()
        except:
            pass
    
    return all_ips


def get_system_info():
    """Get comprehensive system information.
    
    Returns:
        dict: Dictionary containing system information
    """
    info = {
        "os": detect_operating_system(),
        "os_detail": platform.platform(),
        "system_name": get_system_name(),
        "ip_address": get_ip_address(),
        "public_ip": get_public_IP(),
        "all_ip_addresses": get_all_ip_addresses(),
        "slurm_status": are_we_on_slurm_system(),
        "python_version": sys.version.split()[0],
        "architecture": platform.machine(),
    }
    
    # Add SLURM-specific info if on SLURM
    if info["slurm_status"]:
        info["slurm_node_name"] = os.environ.get("SLURMD_NODENAME", "N/A")
        info["slurm_job_id"] = os.environ.get("SLURM_JOB_ID", "N/A")
        info["slurm_cluster_name"] = os.environ.get("SLURM_CLUSTER_NAME", "N/A")
    
    # Add SSH info if available
    ssh_conn = os.environ.get("SSH_CONNECTION")
    if ssh_conn:
        parts = ssh_conn.split()
        if len(parts) >= 4:
            info["ssh_client_ip"] = parts[0]
            info["ssh_server_ip"] = parts[2]
    
    return info
