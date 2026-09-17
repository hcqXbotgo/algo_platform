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
    """Parse aggregate VP utilization from ``flexidag_schdr -t 1000``."""
    if not output:
        return None

    current_core = None
    core_summaries = {}
    core_task_loads = {}
    data_row = re.compile(
        r"^\s*\[\s*\d+\]\s+\S+\s+"
        r"(?P<vp_total>\d+(?:\.\d+)?)\s+"
        r"\(\s*(?P<percent>\d+(?:\.\d+)?)\s*\)\s+"
        r"(?P<total>\d+(?:\.\d+)?)\b"
    )
    summary_row = re.compile(
        r"^\s*(?P<vp_total>\d+(?:\.\d+)?)\s+"
        r"\(\s*(?P<percent>\d+(?:\.\d+)?)\s*\)\s+"
        r"(?P<total>\d+(?:\.\d+)?)\s+with\s+"
        r"(?P<hw_units>\d+)\s+hw\s+unit(?:s)?\s*$",
        re.IGNORECASE,
    )

    def utilization(match):
        vp_total = float(match.group("vp_total"))
        total = float(match.group("total"))
        calculated = vp_total / total * 100.0 if total > 0 else 0.0
        reported = float(match.group("percent"))
        return reported if abs(reported - calculated) < 2.0 else calculated

    for line in output.splitlines():
        core_match = re.search(r"CVCORE[_ ]VP\s*(\d+)", line, re.IGNORECASE)
        if core_match:
            current_core = int(core_match.group(1))
            continue
        if current_core is None:
            continue

        summary_match = summary_row.match(line)
        if summary_match:
            core_summaries[current_core] = utilization(summary_match)
            continue

        match = data_row.match(line)
        if not match:
            continue
        core_task_loads.setdefault(current_core, []).append(utilization(match))

    core_ids = set(core_summaries) | set(core_task_loads)
    core_loads = {
        core_id: core_summaries.get(
            core_id,
            min(100.0, sum(core_task_loads.get(core_id, []))),
        )
        for core_id in core_ids
    }

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


def parse_mal_memory(output):
    """Parse Ambarella MAL memory status into (usage%, used MB, total MB).

    MAL firmware versions use slightly different labels, so accept both
    ``total/used/free`` fields and ``used/total`` pairs with common units.
    """
    if not output:
        return None

    # Current Ambarella firmware reports each MAL pool on an Id line and active
    # allocations on indented ref_cnt lines. Sum them separately.
    pool_pattern = re.compile(
        r"\bId\s*\[\s*\d+\s*\]\s+Pa\s+0x([0-9a-f]+)\s*-\s*0x([0-9a-f]+)",
        re.IGNORECASE,
    )
    allocation_pattern = re.compile(
        r"^\s+Pa\s+0x([0-9a-f]+)\s*-\s*0x([0-9a-f]+)\s+ref_cnt\s*:\s*(\d+)",
        re.IGNORECASE | re.MULTILINE,
    )
    pools = pool_pattern.findall(output)
    if pools:
        total_bytes = sum(max(0, int(end, 16) - int(start, 16)) for start, end in pools)
        allocations = allocation_pattern.findall(output)
        used_bytes = sum(
            max(0, int(end, 16) - int(start, 16))
            for start, end, ref_count in allocations
            if int(ref_count) > 0
        )
        total_mb = total_bytes / (1024.0 * 1024.0)
        used_mb = used_bytes / (1024.0 * 1024.0)
        return (used_mb / total_mb * 100.0 if total_mb else 0.0, used_mb, total_mb)

    unit_multiplier = {
        "b": 1.0 / (1024.0 * 1024.0),
        "kb": 1.0 / 1024.0,
        "kib": 1.0 / 1024.0,
        "mb": 1.0,
        "mib": 1.0,
        "gb": 1024.0,
        "gib": 1024.0,
    }

    def value_for(label):
        match = re.search(
            rf"\b{label}\b\s*(?:memory|size|bytes)?\s*[:=]?\s*"
            rf"([0-9]+(?:\.[0-9]+)?)\s*(bytes?|kib?|mib?|gib?)?",
            output,
            re.IGNORECASE,
        )
        if not match:
            return None
        unit = (match.group(2) or "mb").lower()
        if unit == "byte":
            unit = "b"
        elif unit == "k":
            unit = "kb"
        elif unit == "m":
            unit = "mb"
        elif unit == "g":
            unit = "gb"
        return float(match.group(1)) * unit_multiplier.get(unit, 1.0)

    total_mb = value_for("total")
    used_mb = value_for("used")
    free_mb = value_for("free")

    if total_mb is None or used_mb is None:
        pair = re.search(
            r"(?:used|usage)\s*[/(:]\s*([0-9]+(?:\.[0-9]+)?)\s*"
            r"(?:/|of)\s*([0-9]+(?:\.[0-9]+)?)\s*(bytes?|kib?|mib?|gib?)?",
            output,
            re.IGNORECASE,
        )
        if pair:
            unit = (pair.group(3) or "mb").lower()
            multiplier = unit_multiplier.get(unit, 1.0)
            used_mb = float(pair.group(1)) * multiplier
            total_mb = float(pair.group(2)) * multiplier

    if total_mb is None and used_mb is not None and free_mb is not None:
        total_mb = used_mb + free_mb
    if used_mb is None and total_mb is not None and free_mb is not None:
        used_mb = total_mb - free_mb
    if total_mb is None or used_mb is None or total_mb <= 0:
        return None

    used_mb = max(0.0, used_mb)
    return (used_mb / total_mb * 100.0, used_mb, total_mb)


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


def parse_ambarella_ddr(output):
    """Parse ``svc_sys dram_traffic`` output into MB/s and utilization."""
    if not output:
        return None

    # Strip terminal decoration before parsing line-oriented RTOS output.
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output).replace("\x00", "")
    module_names = {
        "cpu": "cpu",
        "dsp": "dsp",
        "peri": "peri",
        "nvporc": "nvporc",
        "nvp": "nvp",
    }
    module_pattern = re.compile(
        r"^\s*\[(CPU|DSP|PERI|NVPORC|NVP)\s*\]\s*"
        r"\d+(?:\.\d+)?\s*MB\s*\((\d+)\)\s*,\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*percentage",
        re.IGNORECASE,
    )
    total_pattern = re.compile(
        r"\[Utilization\]\s*([0-9]+(?:\.[0-9]+)?)\s*percentage\s*,\s*"
        r"used/avail\((\d+)\s*/\s*(\d+)\)\s*bytes",
        re.IGNORECASE,
    )
    interval_pattern = re.compile(
        r"\[Measured\s+Interval\]\s*(\d+(?:\.\d+)?)\s*ms",
        re.IGNORECASE,
    )

    samples = []
    current = {"modules": {}}

    def finish_sample(interval_ms):
        modules = current.get("modules", {})
        if not {"cpu", "dsp"}.issubset(modules) or "total_bytes" not in current:
            return
        interval_seconds = interval_ms / 1000.0
        if interval_seconds <= 0:
            return

        result = {"measured_interval_ms": interval_ms}
        for key in module_names.values():
            module_bytes, occupancy = modules.get(key, (0, 0.0))
            result[key] = module_bytes / (1024.0 * 1024.0) / interval_seconds
            result[f"{key}_occupancy"] = occupancy

        result["total_occupancy"] = current["total_occupancy"]
        result["total"] = current["total_bytes"] / (1024.0 * 1024.0) / interval_seconds
        available_bytes_per_second = current["available_bytes"] / interval_seconds
        result["available"] = available_bytes_per_second / (1024.0 * 1024.0)
        # The command is configured for a 64-bit DRAM bus. Available bandwidth
        # therefore exposes the effective transfer rate without another RTOS call.
        bus_width_bits = 64
        result["bus_width_bits"] = bus_width_bits
        result["ddr_data_rate_mts"] = (
            available_bytes_per_second / (bus_width_bits / 8.0) / 1_000_000.0
        )
        result["ddr_clock_mhz"] = result["ddr_data_rate_mts"] / 2.0
        result["component_total"] = sum(result[key] for key in module_names.values())
        result["unattributed"] = result["total"] - result["component_total"]
        tolerance = max(0.01, result["total"] * 0.001)
        result["component_consistent"] = abs(result["unattributed"]) <= tolerance
        result["unattributed_occupancy"] = (
            result["unattributed"] / result["available"] * 100.0
            if result["available"] > 0
            else 0.0
        )
        samples.append(result)

    for line in output.splitlines():
        module_match = module_pattern.match(line)
        if module_match:
            key = module_names[module_match.group(1).strip().lower()]
            # A new CPU line after a complete total starts another sample even
            # on firmware that omits the heading or interval separator.
            if key == "cpu" and "cpu" in current["modules"] and "total_bytes" in current:
                finish_sample(1000.0)
                current = {"modules": {}}
            current["modules"][key] = (
                int(module_match.group(2)),
                float(module_match.group(3)),
            )
            continue

        total_match = total_pattern.search(line)
        if total_match:
            current["total_occupancy"] = float(total_match.group(1))
            current["total_bytes"] = int(total_match.group(2))
            current["available_bytes"] = int(total_match.group(3))
            continue

        interval_match = interval_pattern.search(line)
        if interval_match:
            finish_sample(float(interval_match.group(1)))
            current = {"modules": {}}

    # Accept a complete final sample even when this firmware omits the interval
    # line; the command itself requests a 1000 ms measurement window.
    if current.get("modules") and "total_bytes" in current:
        finish_sample(1000.0)

    if not samples:
        return None
    result = samples[-1]
    result["sample_count"] = len(samples)
    return result


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
        "extra_memory": {
            "name": "mal",
            "source": "mal",
            "command": "cat /proc/ambarella/AmbaMalStatus",
            "parser": parse_mal_memory,
        },
        "ddr": {
            "source": "ambarella_serial",
            "transport": "serial",
            "mode": "poll",
            "command": "svc_sys dram_traffic 1000 2 1 64",
            "timeout": 6.0,
            "idle_timeout": 0.6,
            "minimum_wait": 2.5,
            "connect_attempts": 2,
            "open_delay": 0.5,
            "sync_attempts": 3,
            "sync_timeout": 1.5,
            "completion_pattern": r"(?:^|[\r\n])[a-z]:[^\r\n>]*>\s*$",
            "required_keys": ("cpu", "dsp", "peri", "nvporc", "nvp", "total"),
            "parser": parse_ambarella_ddr,
        },
    },
    "falcon2": {
        "probe": "[ -r /proc/vssdk/npu ] || [ -r /proc/vssdk/mmz ]",
        "npu": {"command": "cat /proc/vssdk/npu", "parser": parse_npu_common},
        "cpu": COMMON_CPU,
        "memory": COMMON_MEMORY,
        "extra_memory": {"command": "cat /proc/vssdk/mmz", "parser": parse_memory},
        "ddr": {
            "source": "vssdk",
            "mode": "poll",
            "local_path": "tools/ddr/ddr_bandwidth.sh",
            "remote_path": "/userdata/ddr_bandwidth.sh",
            "command": "cd {tool_dir} && ./{tool_name} -p 100 -f {freq} -w 32 -b 0x100000 -t 1 -d 0xf0000000 -c 2 -n 1",
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
            "local_path": "tools/ddr/rk-msch-probe-for-user-64bit-1",
            "remote_path": "/userdata/rk-msch-probe-for-user-64bit-1",
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
