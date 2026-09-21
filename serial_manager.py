# -*- coding: utf-8 -*-
"""Thread-safe serial transport for the Ambarella RTOS console."""

import re
import threading
import time

import serial
from serial.tools import list_ports


class SerialManager:
    """Own a reusable 8N1 serial connection."""

    def __init__(self):
        self._serial = None
        self._lock = threading.RLock()
        self.port = None
        self.baudrate = 115200
        self.line_ending = "\n"

    @staticmethod
    def available_ports():
        def sort_key(port_info):
            match = re.match(r"COM(\d+)$", port_info.device, re.IGNORECASE)
            return (0, int(match.group(1))) if match else (1, port_info.device.lower())

        return sorted(list(list_ports.comports()), key=sort_key)

    @property
    def is_connected(self):
        return bool(self._serial and self._serial.is_open)

    def connect(self, port, baudrate=115200):
        port = str(port or "").strip()
        if not port:
            return False, "请选择串口"

        try:
            baudrate = int(baudrate)
            if baudrate <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return False, "波特率必须是正整数"

        with self._lock:
            self.disconnect()
            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0,
                    write_timeout=2,
                )
                self.port = port
                self.baudrate = baudrate
                return True, f"串口已连接: {port} @ {baudrate} 8N1"
            except Exception as exc:
                self._serial = None
                self.port = None
                return False, f"串口连接失败: {exc}"

    def disconnect(self):
        with self._lock:
            serial_port = self._serial
            self._serial = None
            if serial_port:
                try:
                    serial_port.close()
                except Exception:
                    pass

    def read_available(self, max_bytes=65536):
        if not self._lock.acquire(blocking=False):
            return ""
        try:
            if not self.is_connected:
                return ""
            waiting = min(self._serial.in_waiting, max_bytes)
            if waiting <= 0:
                return ""
            return self._serial.read(waiting).decode("utf-8", errors="replace").replace("\x00", "")
        finally:
            self._lock.release()

    def send(self, data):
        with self._lock:
            if not self.is_connected:
                return False, "串口未连接"
            try:
                payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
                self._serial.write(payload)
                self._serial.flush()
                return True, "发送成功"
            except Exception as exc:
                return False, f"串口发送失败: {exc}"

    def send_command(self, command):
        command = str(command or "").rstrip("\r\n")
        return self.send(command + self.line_ending)

    def execute_command(
        self,
        command,
        timeout=5.0,
        idle_timeout=0.3,
        minimum_wait=0.0,
        completion_markers=None,
        completion_pattern=None,
        cancel_event=None,
    ):
        """Execute one command and optionally wait for a complete console prompt."""
        with self._lock:
            if not self.is_connected:
                return False, "串口未连接"
            if cancel_event is not None and cancel_event.is_set():
                return False, "串口命令已取消"
            try:
                self._serial.reset_input_buffer()
                payload = str(command or "").rstrip("\r\n") + self.line_ending
                self._serial.write(payload.encode("utf-8"))
                self._serial.flush()

                if isinstance(completion_markers, str):
                    completion_markers = (completion_markers,)
                marker_bytes = tuple(
                    marker.encode("utf-8")
                    for marker in (completion_markers or ())
                    if marker
                )
                completion_regex = (
                    re.compile(completion_pattern.encode("utf-8"), re.IGNORECASE)
                    if completion_pattern
                    else None
                )
                has_completion_rule = bool(marker_bytes or completion_regex)

                response = bytearray()
                started_at = time.monotonic()
                deadline = started_at + float(timeout)
                last_data_at = None
                completed = False
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        return False, "串口命令已取消"
                    waiting = self._serial.in_waiting
                    if waiting:
                        response.extend(self._serial.read(waiting))
                        last_data_at = time.monotonic()
                        marker_found = marker_bytes and any(
                            marker in response for marker in marker_bytes
                        )
                        pattern_found = completion_regex and completion_regex.search(response)
                        if marker_found or pattern_found:
                            completed = True
                            break
                    elif (
                        not has_completion_rule
                        and last_data_at is not None
                        and time.monotonic() - started_at >= float(minimum_wait)
                        and time.monotonic() - last_data_at >= idle_timeout
                    ):
                        completed = True
                        break
                    else:
                        time.sleep(0.02)

                output = bytes(response).decode("utf-8", errors="replace").replace("\x00", "")
                if has_completion_rule and not completed:
                    tail = " | ".join(line.strip() for line in output.splitlines() if line.strip())
                    if len(tail) > 500:
                        tail = tail[-500:]
                    return False, f"等待串口命令结束标记超时，回显: {tail or '<empty>'}"
                return True, output
            except Exception as exc:
                return False, f"串口命令执行失败: {exc}"
