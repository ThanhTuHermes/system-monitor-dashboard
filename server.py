#!/usr/bin/env python3
"""Dashboard Giám Sát Hệ Thống — Server realtime."""

import os
import json
import time
import subprocess
import psutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime

# ── Lấy thông tin service systemd ─────────────────────────────────────────────


def get_service_info(service_name):
    """Lấy thông tin service từ systemctl."""
    info = {
        "name": service_name,
        "active": False,
        "status": "không rõ",
        "pid": 0,
        "memory_bytes": 0,
        "memory_peak_bytes": 0,
        "cpu_seconds": 0.0,
        "tasks": 0,
        "uptime_seconds": 0,
        "started_at": "",
        "description": "",
        "child_count": 0,
        "port": 0,
    }

    try:
        # systemctl status
        result = subprocess.run(
            ["systemctl", "status", service_name, "--no-pager", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.split("\n")

        for line in lines:
            if line.startswith("●"):
                # Parse: ● service.service - Description
                parts = line.split(" - ", 1)
                if len(parts) > 1:
                    info["description"] = parts[1].strip()
            elif "Active:" in line:
                if "active (running)" in line:
                    info["active"] = True
                    info["status"] = "đang chạy"
                elif "active (exited)" in line:
                    info["status"] = "đã dừng (exit)"
                elif "failed" in line:
                    info["status"] = "lỗi"
                else:
                    info["status"] = line.split("Active:")[1].split(";")[0].strip()
            elif "Memory:" in line:
                # "Memory: 363.5M (peak: 519.9M)"
                parts = line.split(":")[1].strip().split(" ")
                if parts:
                    info["memory_bytes"] = _parse_size(parts[0])
                if "peak:" in line:
                    peak = line.split("peak:")[1].split(")")[0].strip()
                    info["memory_peak_bytes"] = _parse_size(peak)
            elif "CPU:" in line:
                # "CPU: 2min 16.413s"
                cpu_str = line.split("CPU:")[1].strip()
                info["cpu_seconds"] = _parse_cpu_time(cpu_str)
            elif "Tasks:" in line:
                info["tasks"] = int(line.split("Tasks:")[1].split("(")[0].strip())
            elif "Main PID:" in line:
                info["pid"] = int(line.split("Main PID:")[1].split("(")[0].strip())
            elif "since" in line and "ago" in line:
                # "Active: active (running) since Wed 2026-06-17 17:00:43 UTC; 3h 28min ago"
                try:
                    since_part = line.split("since")[1].split(";")[0].strip()
                    ago_part = line.split(";")[1].strip() if ";" in line else ""
                    info["started_at"] = since_part
                    if "ago" in ago_part:
                        info["uptime_seconds"] = _parse_uptime(
                            ago_part.replace(" ago", "")
                        )
                except Exception:
                    pass

        # Đếm process con
        if info["pid"] > 0:
            try:
                parent = psutil.Process(info["pid"])
                info["child_count"] = len(parent.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    except Exception as e:
        info["status"] = f"lỗi: {str(e)}"

    return info


def get_hermes_info():
    """Lấy thông tin chi tiết Hermes Agent."""
    info = get_service_info("hermes")

    # Port dashboard
    info["port"] = 9119

    # Parse journal log gần nhất
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "hermes",
                "--no-pager",
                "--since",
                "10 min ago",
                "-o",
                "short-iso",
                "--output-fields=MESSAGE",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        info["recent_logs"] = (
            result.stdout.strip().split("\n")[-10:] if result.stdout.strip() else []
        )
    except Exception:
        info["recent_logs"] = []

    # Child processes
    if info["pid"] > 0:
        try:
            parent = psutil.Process(info["pid"])
            children = parent.children(recursive=True)
            info["children"] = []
            for c in children:
                try:
                    mem = c.memory_info()
                    info["children"].append(
                        {
                            "pid": c.pid,
                            "name": c.name(),
                            "memory_mb": round(mem.rss / 1024 / 1024, 1),
                            "cpu_percent": c.cpu_percent(interval=0),
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            info["children"] = []

    return info


def get_9router_info():
    """Lấy thông tin chi tiết 9Router."""
    info = get_service_info("9router")
    info["port"] = 20128

    # Parse journal log gần nhất — thống kê request
    try:
        result = subprocess.run(
            ["journalctl", "-u", "9router", "--no-pager", "--since", "5 min ago"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        logs = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Đếm request thành công / lỗi
        success = sum(1 for l in logs if "succeeded" in l)
        errors = sum(1 for l in logs if "[ERROR]" in l or "END (ERROR)" in l)
        pending = sum(1 for l in logs if "[PENDING] START" in l)

        info["stats"] = {
            "success_count": success,
            "error_count": errors,
            "pending_count": pending,
        }

        # Lấy log gần nhất
        info["recent_logs"] = logs[-12:] if logs else []

        # Providers đang dùng
        providers = set()
        for l in logs:
            if "provider=" in l:
                prov = l.split("provider=")[1].split("|")[0].split()[0].strip()
                providers.add(prov)
            elif "[ROUTING]" in l:
                prov = (
                    l.split("[ROUTING]")[1].split("→")[0].strip().split("/")[-1]
                    if "→" in l
                    else ""
                )
                if prov:
                    providers.add(prov)
        info["active_providers"] = list(providers)

    except Exception:
        info["stats"] = {"success_count": 0, "error_count": 0, "pending_count": 0}
        info["recent_logs"] = []
        info["active_providers"] = []

    return info


def _parse_size(s):
    """Parse '363.5M' / '519.9M' / '41.2G' -> bytes."""
    s = s.strip()
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, mult in multipliers.items():
        if s.upper().endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _parse_cpu_time(s):
    """Parse '2min 16.413s' -> seconds."""
    parts = s.strip().split()
    total = 0.0
    for p in parts:
        if "min" in p:
            try:
                total += float(p.replace("min", "")) * 60
            except ValueError:
                pass
        elif "s" in p:
            try:
                total += float(p.replace("s", ""))
            except ValueError:
                pass
    return total


def _parse_uptime(s):
    """Parse '3h 28min' -> seconds."""
    parts = s.strip().split()
    total = 0
    for p in parts:
        if "day" in p:
            try:
                total += int(p.replace("days", "").replace("day", "")) * 86400
            except ValueError:
                pass
        elif "h" in p:
            try:
                total += int(p.replace("h", "")) * 3600
            except ValueError:
                pass
        elif "min" in p:
            try:
                total += int(p.replace("min", "").replace("minutes", "")) * 60
            except ValueError:
                pass
    return total


# ── Thu thập tất cả metrics ────────────────────────────────────────────────────


def get_metrics():
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0)
    cpu_count = psutil.cpu_count()
    cpu_freq = psutil.cpu_freq()
    load_avg = os.getloadavg()
    cpu_times = psutil.cpu_times_percent(interval=0)
    per_cpu = psutil.cpu_percent(interval=0, percpu=True)

    # Memory
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disk
    disk_partitions = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_partitions.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )
        except PermissionError:
            pass

    # Network
    net_io = psutil.net_io_counters()
    interfaces = {}
    per_nic = psutil.net_io_counters(pernic=True)
    addrs = psutil.net_if_addrs()
    for iface, counters in per_nic.items():
        ips = []
        if iface in addrs:
            for addr in addrs[iface]:
                if addr.family.name == "AF_INET":
                    ips.append(addr.address)
        interfaces[iface] = {
            "bytes_sent": counters.bytes_sent,
            "bytes_recv": counters.bytes_recv,
            "packets_sent": counters.packets_sent,
            "packets_recv": counters.packets_recv,
            "ips": ips,
        }

    # Uptime / Boot
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_sec = time.time() - psutil.boot_time()

    return {
        "timestamp": time.time(),
        "cpu": {
            "percent": cpu_percent,
            "count": cpu_count,
            "freq_current": cpu_freq.current if cpu_freq else 0,
            "freq_max": cpu_freq.max if cpu_freq else 0,
            "load_avg_1m": load_avg[0],
            "load_avg_5m": load_avg[1],
            "load_avg_15m": load_avg[2],
            "times": {
                "user": cpu_times.user,
                "system": cpu_times.system,
                "idle": cpu_times.idle,
                "iowait": getattr(cpu_times, "iowait", 0),
            },
            "per_cpu": per_cpu,
        },
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "disk": {
            "partitions": disk_partitions,
            "io": {
                "read_bytes": (
                    psutil.disk_io_counters().read_bytes
                    if psutil.disk_io_counters()
                    else 0
                ),
                "write_bytes": (
                    psutil.disk_io_counters().write_bytes
                    if psutil.disk_io_counters()
                    else 0
                ),
            },
        },
        "network": {
            "total_sent": net_io.bytes_sent,
            "total_recv": net_io.bytes_recv,
            "total_packets_sent": net_io.packets_sent,
            "total_packets_recv": net_io.packets_recv,
            "interfaces": interfaces,
        },
        "system": {
            "boot_time": boot_time.isoformat(),
            "uptime_seconds": uptime_sec,
            "process_count": len(psutil.pids()),
        },
        "hermes": get_hermes_info(),
        "router9": get_9router_info(),
    }


# ── HTTP Handler ─────────────────────────────────────────────────────────────


class DashboardHandler(SimpleHTTPRequestHandler):
    """Phục vụ index.html + /api/metrics."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(get_metrics()).encode())
            return

        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), "index.html"), "rb") as f:
                self.wfile.write(f.read())
            return

        super().do_GET()

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(format, *args)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    HOST = "0.0.0.0"
    PORT = 8080
    print(f"🖥️  Dashboard Giám Sát Hệ Thống")
    print(f"📡 http://0.0.0.0:{PORT}")
    print(f"📡 http://localhost:{PORT}")
    print(f"Nhấn Ctrl+C để dừng\n")

    server = HTTPServer((HOST, PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server đã dừng.")
        server.server_close()
