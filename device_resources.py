# -*- coding: utf-8 -*-
"""Device resource command and parser registry."""

import re


def parse_npu_common(output):
    if not output:
        return None

    core0_match = re.search(r"Core0:\s*([\d.]+)%", output, re.IGNORECASE)
    core1_match = re.search(r"Core1:\s*([\d.]+)%", output, re.IGNORECASE)
    if core0_match and core1_match:
        core0 = float(core0_match.group(1))
        core1 = float(core1_match.group(1))
        return {"core0": core0, "core1": core1, "avg": (core0 + core1) / 2.0, "core_count": 2}

    in_runtime_section = False
    utilization_index = None
    cluster_loads = {}
    for line in output.splitlines():
        stripped = line.strip()
        if "npu runtime info" in stripped.lower():
            in_runtime_section = True
            continue
        if not in_runtime_section:
            continue
        if stripped.startswith("-"):
            break
        parts = stripped.split()
        if utilization_index is None:
            lowered = [part.lower() for part in parts]
            if "clusterid" in lowered and "hw_utilization" in lowered:
                utilization_index = lowered.index("hw_utilization")
            continue
        if parts and parts[0].isdigit() and len(parts) > utilization_index:
            cluster_loads[int(parts[0])] = float(parts[utilization_index].rstrip("%"))

    if not cluster_loads:
        return None
    core0 = cluster_loads.get(0, 0.0)
    core1 = cluster_loads.get(1, 0.0)
    return {"core0": core0, "core1": core1, "avg": (core0 * 4.0 + core1 * 2.0) / 6.0, "core_count": 2}


def parse_ambarella_npu(output):
    """Parse VP utilization from ``flexidag_schdr -t 1000``."""
    if not output:
        return None

    current_core = None
    core_loads = {}
    data_row = re.compile(
        r"^\s*\[\s*\d+\]\s+\S+\s+"
        r"(?P<vp_total>\d+(?:\.\d+)?)\s+"
        r"\(\s*(?P<percent>\d+(?:\.\d+)?)\s*\)\s+"
        r"(?P<total>\d+(?:\.\d+)?)\b"
    )
    for line in output.splitlines():
        core_match = re.search(r"CVCORE[_ ]VP\s*(\d+)", line, re.IGNORECASE)
        if core_match:
            current_core = int(core_match.group(1))
            continue
        match = data_row.match(line)
        if current_core is None or not match:
            continue
        vp_total = float(match.group("vp_total"))
        total = float(match.group("total"))
        calculated = vp_total / total * 100.0 if total > 0 else 0.0
        reported = float(match.group("percent"))
        core_loads[current_core] = reported if abs(reported - calculated) < 2.0 else calculated

    if not core_loads:
        return None
    core0 = core_loads.get(0, 0.0)
    core1 = core_loads.get(1, 0.0)
    return {
        "core0": core0,
        "core1": core1,
        "avg": sum(core_loads.values()) / len(core_loads),
        "core_count": len(core_loads),
    }


def parse_memory(output):
    if not output:
        return None
    mmz = re.search(
        r"mmz\s+use\s+summary:\s*total=(\d+(?:\.\d+)?)KB\s+"
        r"used=(\d+(?:\.\d+)?)KB\s+free=(\d+(?:\.\d+)?)KB",
        output,
        re.IGNORECASE,
    )
    if mmz:
        total_mb = float(mmz.group(1)) / 1024.0
        used_mb = float(mmz.group(2)) / 1024.0
        return (used_mb / total_mb * 100.0 if total_mb else 0.0, used_mb, total_mb)
    for line in output.splitlines():
        parts = line.split()
        if parts and parts[0].rstrip(":").lower() == "mem" and len(parts) >= 3:
            total_mb, used_mb = float(parts[1]), float(parts[2])
            return (used_mb / total_mb * 100.0 if total_mb else 0.0, used_mb, total_mb)
    return None


def parse_cpu_stat(samples):
    if not samples or len(samples) < 2 or not samples[0] or not samples[1]:
        return None
    first = list(map(int, samples[0].split()[1:]))
    second = list(map(int, samples[1].split()[1:]))
    size = min(len(first), len(second))
    diffs = [second[index] - first[index] for index in range(size)]
    total = sum(diffs)
    if total <= 0 or len(diffs) < 4:
        return None
    return (1.0 - diffs[3] / total) * 100.0


def parse_falcon2_ddr_line(line):
    match = re.match(
        r"\s*(total(?:_wr|_rd)?)\s+avg\s+bw\s*=\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*MB/s\s*,\s*"
        r"avg\s+occupancy\s*=\s*([0-9]+(?:\.[0-9]+)?)%",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None
    metric = match.group(1).lower()
    return {metric: float(match.group(2)), f"{metric}_occupancy": float(match.group(3))}


COMMON_CPU = {
    "command": "cat /proc/stat | grep '^cpu '",
    "samples": 2,
    "sample_delay": 0.5,
    "parser": parse_cpu_stat,
}
COMMON_MEMORY = {"command": "free -m", "parser": parse_memory}


DEVICE_RESOURCE_PROFILES = {
    "ambarella": {
        "probe": "command -v flexidag_schdr >/dev/null 2>&1",
        "npu": {
            "command": "flexidag_schdr -t 1000",
            "parser": parse_ambarella_npu,
            "core_count": 1,
            "smoothing_alpha": 0.3,
        },
        "cpu": COMMON_CPU,
        "memory": COMMON_MEMORY,
        "extra_memory": None,
        "ddr": None,
    },
    "falcon2": {
        "probe": "[ -r /proc/vssdk/npu ] || [ -r /proc/vssdk/mmz ]",
        "npu": {"command": "cat /proc/vssdk/npu", "parser": parse_npu_common},
        "cpu": COMMON_CPU,
        "memory": COMMON_MEMORY,
        "extra_memory": {"command": "cat /proc/vssdk/mmz", "parser": parse_memory},
        "ddr": {
            "source": "vssdk",
            "command": "cd /userdata && ./ddr_bandwidth.sh -p 100 -f {freq} -w 32 -b 0x100000 -t 1 -d 0xf0000000 -c 2 -n 1",
            "stop_command": "pkill -f '[d]dr_bandwidth' >/dev/null 2>&1 || true",
            "line_parser": parse_falcon2_ddr_line,
        },
    },
    "falcon": {
        "probe": "true",
        "npu": {"command": "cat /sys/kernel/debug/rknpu/load", "parser": parse_npu_common},
        "cpu": COMMON_CPU,
        "memory": COMMON_MEMORY,
        "extra_memory": None,
        "ddr": {
            "source": "rknpu",
            "command": "cd {tool_dir} && ./{tool_name} -c rk3576 -f {freq} -l 2 2>&1",
            "stop_command": "pkill -f '[r]k-msch-probe-for-user-64bit-1' >/dev/null 2>&1 || true",
        },
    },
}


DEVICE_DETECTION_COMMAND = (
    "if [ -r /proc/vssdk/npu ] || [ -r /proc/vssdk/mmz ]; then echo falcon2; "
    "elif command -v flexidag_schdr >/dev/null 2>&1; then echo ambarella; "
    "else echo falcon; fi"
)


def get_resource_profile(name):
    return DEVICE_RESOURCE_PROFILES.get(name, DEVICE_RESOURCE_PROFILES["falcon"])
