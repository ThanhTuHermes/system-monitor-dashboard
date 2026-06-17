#!/usr/bin/env python3
"""System Monitor Dashboard — Real-time server."""

import os
import json
import time
import psutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# ── Metrics collector ────────────────────────────────────────────────────────

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
            disk_partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            })
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

    # Process count
    proc_count = len(psutil.pids())

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
                "read_bytes": psutil.disk_io_counters().read_bytes if psutil.disk_io_counters() else 0,
                "write_bytes": psutil.disk_io_counters().write_bytes if psutil.disk_io_counters() else 0,
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
            "process_count": proc_count,
        },
    }


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves both static files (index.html) and /api/metrics endpoint."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(get_metrics()).encode())
            return

        # Serve dashboard.html at root
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), "index.html"), "rb") as f:
                self.wfile.write(f.read())
            return

        # Fallback to file system
        super().do_GET()

    def log_message(self, format, *args):
        # Quieter logs
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(format, *args)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    HOST = "0.0.0.0"
    PORT = 8080
    print(f"🖥️  System Monitor Dashboard")
    print(f"📡 http://0.0.0.0:{PORT}")
    print(f"📡 http://localhost:{PORT}")
    print(f"Press Ctrl+C to stop\n")

    server = HTTPServer((HOST, PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")
        server.server_close()
