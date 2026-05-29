# -*- coding: utf-8 -*-
"""
WiFi性能测试模块
功能：使用iperf3进行UDP带宽测试，测量抖动、丢包率、延迟、RSSI和协商速率
"""

import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime

from log_manager import LogManager


log_manager = LogManager()


class WiFiPerfTester:
    """WiFi性能测试器"""

    def __init__(self, device_ip=None):
        self.device_ip = device_ip
        self.iperf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iperf3.exe")
        self.test_results = []
        self._current_process = None
        self._cancel_requested = False

    def set_device_ip(self, device_ip):
        """设置设备IP地址"""
        self.device_ip = device_ip

    def cancel_current_test(self):
        """取消当前正在执行的本机 iperf3 测试进程。"""
        self._cancel_requested = True
        process = self._current_process
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _open_ssh(self, timeout=10):
        """打开SSH连接；失败时尝试通过ADB启动设备端SSH服务后重试一次。"""
        if not self.device_ip:
            raise RuntimeError("未设置设备IP地址")

        import paramiko

        def connect_once():
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                self.device_ip,
                port=22,
                username="root",
                password="",
                timeout=timeout,
                banner_timeout=2,
                auth_timeout=3,
                allow_agent=False,
                look_for_keys=False,
            )
            return ssh_client

        try:
            return connect_once()
        except Exception as first_error:
            log_manager.warning(
                f"[WiFiTest] SSH连接失败，尝试通过ADB启动SSH服务: {first_error}"
            )
            from device_manager import DeviceManager

            adb_success, adb_msg = DeviceManager().ensure_ssh_service_via_adb()
            if not adb_success:
                raise RuntimeError(f"ADB启动SSH服务失败: {adb_msg}") from first_error
            return connect_once()

    @staticmethod
    def _safe_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _decode_output(data):
        if data is None:
            return ""
        if isinstance(data, str):
            return data
        for encoding in ("utf-8", "gbk", "cp936", "latin-1"):
            try:
                return data.decode(encoding)
            except Exception:
                continue
        return data.decode("utf-8", errors="ignore")

    def _run_ssh_command(self, ssh, command, timeout=5):
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        stdout_text = self._decode_output(stdout.read()).strip()
        stderr_text = self._decode_output(stderr.read()).strip()
        return exit_status, stdout_text, stderr_text

    def _detect_wifi_interfaces(self, ssh):
        interfaces = []
        try:
            _, output, _ = self._run_ssh_command(ssh, "iw dev", timeout=5)
            for match in re.finditer(r"Interface\s+([^\s]+)", output):
                iface = match.group(1).strip()
                if iface and iface not in interfaces:
                    interfaces.append(iface)
        except Exception as e:
            log_manager.debug(f"[WiFiInfo] iw dev 探测失败: {e}")

        fallback = [
            "wlan0",
            "wlan1",
            "wlp0s20f3",
            "wlp1s0",
            "wlp2s0",
            "ath0",
            "ra0",
            "ap0",
        ]
        for iface in fallback:
            if iface not in interfaces:
                interfaces.append(iface)
        return interfaces

    @staticmethod
    def _extract_rssi(text):
        if not text:
            return None

        patterns = [
            r"(?:signal(?:\s+avg)?|signal average)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*dBm",
            r"\bsignal\s*[:=]\s*(-?\d+(?:\.\d+)?)\b",
            r"(?:Signal level|signal level)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*dBm",
            r"(?:Signal level|signal level)\s*[:=]\s*(-?\d+(?:\.\d+)?)\b",
            r"(?:RSSI)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*dBm",
            r"(?:RSSI)\s*[:=]\s*(-?\d+(?:\.\d+)?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))

        # /proc/net/wireless 兜底，level 列通常也是负值
        match = re.search(r"^\s*\S+:\s*\d+\s+(-?\d+(?:\.\d+)?)\s+", text, re.MULTILINE)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _extract_link_speed_details(text):
        if not text:
            return None, None

        def parse_speed(pattern, source):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2).lower()
                if unit.startswith("k"):
                    value /= 1000.0
                return value, source
            return None, None

        # iw dev wlan0 link 同时会输出 rx/tx bitrate，协商速率优先使用 tx。
        patterns = [
            (r"\btx\s+bitrate\s*[:=]\s*([\d.]+)\s*(MBit/s|Mbit/s|Mb/s|Mbps)", "tx bitrate"),
            (r"\btx\s+bitrate\s*[:=]\s*([\d.]+)\s*(KBit/s|Kbit/s|Kb/s|Kbps)", "tx bitrate"),
            (r"\brx\s+bitrate\s*[:=]\s*([\d.]+)\s*(MBit/s|Mbit/s|Mb/s|Mbps)", "rx bitrate"),
            (r"\brx\s+bitrate\s*[:=]\s*([\d.]+)\s*(KBit/s|Kbit/s|Kb/s|Kbps)", "rx bitrate"),
            (r"\bBit\s*Rate\s*[:=]\s*([\d.]+)\s*(MBit/s|Mbit/s|Mb/s|Mbps)", "iwconfig Bit Rate"),
            (r"\bBit\s*Rate\s*[:=]\s*([\d.]+)\s*(KBit/s|Kbit/s|Kb/s|Kbps)", "iwconfig Bit Rate"),
            (r"(?<!rx\s)(?<!tx\s)\bbitrate\s*[:=]\s*([\d.]+)\s*(MBit/s|Mbit/s|Mb/s|Mbps)", "bitrate"),
            (r"(?<!rx\s)(?<!tx\s)\bbitrate\s*[:=]\s*([\d.]+)\s*(KBit/s|Kbit/s|Kb/s|Kbps)", "bitrate"),
        ]
        for pattern, source in patterns:
            value, source = parse_speed(pattern, source)
            if value is not None:
                return value, source
        return None, None

    @staticmethod
    def _extract_link_speed(text):
        value, _ = WiFiPerfTester._extract_link_speed_details(text)
        return value

    def _collect_wifi_info_for_interface(self, ssh, iface):
        info = {
            "interface": iface,
            "rssi": None,
            "link_speed": None,
            "valid": False,
            "source": None,
            "rssi_source": None,
            "link_speed_source": None,
            "link_output": "",
            "iwconfig_output": "",
            "proc_wireless_output": "",
        }

        if not iface:
            return info

        # 1) iw dev <iface> link
        try:
            exit_status, link_output, link_err = self._run_ssh_command(ssh, f"iw dev {iface} link", timeout=5)
            info["link_output"] = link_output
            if link_err:
                log_manager.debug(f"[WiFiInfo] {iface} iw link stderr: {link_err}")
            if link_output:
                log_manager.debug(f"[WiFiInfo] {iface} iw link output: {link_output}")

            link_text = "\n".join(part for part in (link_output, link_err) if part)
            rssi = self._extract_rssi(link_text)
            speed, speed_source = self._extract_link_speed_details(link_text)
            if rssi is not None:
                info["rssi"] = rssi
                info["rssi_source"] = "iw dev link"
                info["valid"] = True
            if speed is not None:
                info["link_speed"] = speed
                info["link_speed_source"] = f"iw dev link {speed_source}"
                info["valid"] = True
            if info["rssi"] is not None and info["link_speed"] is not None:
                info["source"] = "iw dev link"
                return info
            if info["valid"]:
                info["source"] = info["source"] or "iw dev link"
        except Exception as e:
            log_manager.debug(f"[WiFiInfo] {iface} iw dev link 解析失败: {e}")

        # 2) iwconfig <iface>
        try:
            exit_status, iwconfig_output, iwconfig_err = self._run_ssh_command(ssh, f"iwconfig {iface}", timeout=5)
            info["iwconfig_output"] = iwconfig_output
            if iwconfig_err:
                log_manager.debug(f"[WiFiInfo] {iface} iwconfig stderr: {iwconfig_err}")
            if iwconfig_output:
                log_manager.debug(f"[WiFiInfo] {iface} iwconfig output: {iwconfig_output}")

            iwconfig_text = "\n".join(part for part in (iwconfig_output, iwconfig_err) if part)
            rssi = self._extract_rssi(iwconfig_text)
            speed, speed_source = self._extract_link_speed_details(iwconfig_text)
            if rssi is not None:
                info["rssi"] = rssi
                info["rssi_source"] = "iwconfig"
                info["valid"] = True
            if speed is not None:
                info["link_speed"] = speed
                info["link_speed_source"] = f"iwconfig {speed_source}"
                info["valid"] = True
            if info["rssi"] is not None and info["link_speed"] is not None:
                if info["source"] and info["source"] != "iwconfig":
                    info["source"] = f"{info['source']} + iwconfig"
                else:
                    info["source"] = "iwconfig"
                return info
            if info["valid"]:
                if info["source"] and info["source"] != "iwconfig":
                    info["source"] = f"{info['source']} + iwconfig"
                else:
                    info["source"] = "iwconfig"
        except Exception as e:
            log_manager.debug(f"[WiFiInfo] {iface} iwconfig 解析失败: {e}")

        # 3) /proc/net/wireless
        try:
            exit_status, proc_output, proc_err = self._run_ssh_command(ssh, "cat /proc/net/wireless", timeout=5)
            info["proc_wireless_output"] = proc_output
            if proc_err:
                log_manager.debug(f"[WiFiInfo] /proc/net/wireless stderr: {proc_err}")
            if proc_output:
                log_manager.debug(f"[WiFiInfo] /proc/net/wireless output: {proc_output}")

            if proc_output:
                pattern = rf"^\s*{re.escape(iface)}:\s*\d+\s+(-?\d+(?:\.\d+)?)\s+"
                match = re.search(pattern, proc_output, re.MULTILINE)
                if match:
                    info["rssi"] = float(match.group(1))
                    info["rssi_source"] = "/proc/net/wireless"
                    info["valid"] = True
                    if info["source"] and info["source"] != "/proc/net/wireless":
                        info["source"] = f"{info['source']} + /proc/net/wireless"
                    else:
                        info["source"] = "/proc/net/wireless"
                    return info
        except Exception as e:
            log_manager.debug(f"[WiFiInfo] {iface} /proc/net/wireless 解析失败: {e}")

        return info

    def get_wifi_info(self):
        """获取WiFi信息（RSSI和协商速率）

        Returns:
            dict: 包含rssi和link_speed的信息
        """
        if not self.device_ip:
            return {
                "rssi": None,
                "link_speed": None,
                "valid": False,
                "interface": None,
                "source": None,
                "rssi_source": None,
                "link_speed_source": None,
            }

        ssh = None
        try:
            ssh = self._open_ssh(timeout=10)

            interfaces = self._detect_wifi_interfaces(ssh)
            log_manager.debug(f"[WiFiInfo] 探测到接口: {interfaces}")

            def score_info(info):
                score = 0
                if info.get("valid"):
                    score += 10
                if info.get("rssi") is not None:
                    score += 20
                if info.get("link_speed") is not None:
                    score += 20
                if info.get("interface") == "wlan0":
                    score += 5
                if info.get("source") == "iw dev link":
                    score += 3
                return score

            best_info = None
            for iface in interfaces:
                info = self._collect_wifi_info_for_interface(ssh, iface)
                if best_info is None or score_info(info) > score_info(best_info):
                    best_info = info

            if best_info is None:
                best_info = {
                    "rssi": None,
                    "link_speed": None,
                    "valid": False,
                    "interface": None,
                    "source": None,
                    "rssi_source": None,
                    "link_speed_source": None,
                }

            rssi_text = "N/A" if best_info.get("rssi") is None else f"{best_info['rssi']:.0f} dBm"
            speed_text = "N/A" if best_info.get("link_speed") is None else f"{best_info['link_speed']:.1f} Mbps"
            log_manager.info(
                f"[WiFiInfo] device={self.device_ip}, iface={best_info.get('interface')}, "
                f"RSSI={rssi_text}, 协商速率={speed_text}, source={best_info.get('source')}"
            )
            if not best_info.get("valid"):
                log_manager.warning(
                    f"[WiFiInfo] 未能从设备 {self.device_ip} 读取到有效 WiFi 信息，"
                    f"请检查接口名称、驱动输出或连接状态"
                )
            return best_info

        except Exception as e:
            log_manager.error(f"获取WiFi信息失败: {str(e)}", exc_info=True)
            return {
                "rssi": None,
                "link_speed": None,
                "valid": False,
                "interface": None,
                "source": None,
                "rssi_source": None,
                "link_speed_source": None,
            }
        finally:
            try:
                if ssh:
                    ssh.close()
            except Exception:
                pass

    def start_iperf_server(self):
        """在设备上启动iperf3服务器

        Returns:
            tuple: (success, message)
        """
        if not self.device_ip:
            return False, "未设置设备IP地址"

        try:
            ssh = self._open_ssh(timeout=10)

            # 先停止可能存在的iperf3进程
            ssh.exec_command("killall iperf3 2>/dev/null", timeout=5)
            time.sleep(1)

            # 启动iperf3服务器（后台运行）
            stdin, stdout, stderr = ssh.exec_command("iperf3 -s -D", timeout=5)
            stdout.channel.recv_exit_status()

            time.sleep(2)  # 等待服务器启动

            # 检查是否成功启动
            stdin, stdout, stderr = ssh.exec_command("ps aux | grep iperf3 | grep -v grep", timeout=5)
            output = stdout.read().decode("utf-8", errors="ignore").strip()

            ssh.close()

            if "iperf3" in output:
                log_manager.info(f"[WiFiTest] 设备 {self.device_ip} 上的 iperf3 服务器已启动")
                return True, "iperf3服务器启动成功"
            return False, "iperf3服务器启动失败"

        except Exception as e:
            error_msg = f"启动iperf3服务器失败: {str(e)}"
            log_manager.error(error_msg, exc_info=True)
            return False, error_msg

    def stop_iperf_server(self):
        """停止设备上的iperf3服务器"""
        if not self.device_ip:
            return

        try:
            ssh = self._open_ssh(timeout=10)

            ssh.exec_command("killall iperf3", timeout=5)
            ssh.close()

            log_manager.info(f"[WiFiTest] 设备 {self.device_ip} 上的 iperf3 服务器已停止")

        except Exception as e:
            log_manager.error(f"停止iperf3服务器失败: {str(e)}", exc_info=True)

    def _select_metric(self, end_summary, key, prefer_order=("sum_received", "sum", "sum_sent")):
        """按优先级选择 iperf JSON 中的指标来源。"""
        if not isinstance(end_summary, dict):
            return None, None

        candidates = []
        for section_name in prefer_order:
            section = end_summary.get(section_name)
            if isinstance(section, dict) and key in section:
                value = section.get(key)
                candidates.append((section_name, value))
                if value not in (None, "") and value != 0:
                    return value, section_name

        for stream in end_summary.get("streams", []) or []:
            if not isinstance(stream, dict):
                continue
            if key in stream:
                value = stream.get(key)
                candidates.append(("streams", value))
                if value not in (None, "") and value != 0:
                    return value, "streams"
            udp_info = stream.get("udp")
            if isinstance(udp_info, dict) and key in udp_info:
                value = udp_info.get(key)
                candidates.append(("streams.udp", value))
                if value not in (None, "") and value != 0:
                    return value, "streams.udp"

        if candidates:
            return candidates[0][1], candidates[0][0]
        return None, None

    def _measure_ping(self, target_ip, count=4):
        """使用 ping 采集平均延迟和丢包率。"""
        if not target_ip:
            return {
                "avg_latency_ms": None,
                "loss_percent": None,
                "samples": [],
                "output": "",
                "success": False,
            }

        if os.name == "nt":
            cmd = ["ping", "-n", str(count), "-w", "1000", target_ip]
        else:
            cmd = ["ping", "-c", str(count), "-W", "1", target_ip]

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=count * 3 + 5,
            )
            output = self._decode_output(completed.stdout) + "\n" + self._decode_output(completed.stderr)
        except FileNotFoundError as e:
            log_manager.warning(f"[WiFiTest] ping 命令不可用: {e}")
            return {
                "avg_latency_ms": None,
                "loss_percent": None,
                "samples": [],
                "output": "",
                "success": False,
            }
        except subprocess.TimeoutExpired as e:
            output = (self._decode_output(getattr(e, "stdout", "")) or "") + "\n" + (
                self._decode_output(getattr(e, "stderr", "")) or ""
            )
            log_manager.warning(f"[WiFiTest] ping 测试超时: {target_ip}")
            return {
                "avg_latency_ms": None,
                "loss_percent": None,
                "samples": [],
                "output": output.strip(),
                "success": False,
            }

        samples = [
            float(match)
            for match in re.findall(r"(?:time|时间)[=<]\s*([0-9.]+)\s*ms", output, flags=re.IGNORECASE)
        ]

        avg_latency = None
        if samples:
            avg_latency = sum(samples) / len(samples)
        else:
            avg_match = re.search(r"(?:Average|平均)\s*=\s*([0-9.]+)\s*ms", output, re.IGNORECASE)
            if avg_match:
                avg_latency = float(avg_match.group(1))
            else:
                linux_avg = re.search(
                    r"min/avg/max(?:/mdev)?\s*=\s*[\d.]+/([\d.]+)/[\d.]+",
                    output,
                    re.IGNORECASE,
                )
                if linux_avg:
                    avg_latency = float(linux_avg.group(1))

        loss_percent = None
        loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet\s+)?(?:loss|丢失|丢包)", output, re.IGNORECASE)
        if loss_match:
            loss_percent = float(loss_match.group(1))
        else:
            loss_match = re.search(r"Lost\s*=\s*\d+\s*\(([\d.]+)%", output, re.IGNORECASE)
            if loss_match:
                loss_percent = float(loss_match.group(1))
            else:
                loss_match = re.search(r"丢失\s*=\s*\d+\s*\(([\d.]+)%", output, re.IGNORECASE)
                if loss_match:
                    loss_percent = float(loss_match.group(1))

        if avg_latency is not None:
            avg_latency = round(avg_latency, 2)
        if loss_percent is not None:
            loss_percent = round(loss_percent, 2)

        return {
            "avg_latency_ms": avg_latency,
            "loss_percent": loss_percent,
            "samples": samples,
            "output": output.strip(),
            "success": completed.returncode == 0,
        }

    def _extract_interval_series(self, result_json):
        """从 iperf3 intervals 中提取按秒变化的数据，用于单点测试时间轴曲线。"""
        series = []
        for index, interval in enumerate(result_json.get("intervals", []) or []):
            if not isinstance(interval, dict):
                continue

            summary = interval.get("sum")
            if not isinstance(summary, dict):
                summary = None
                for stream in interval.get("streams", []) or []:
                    if not isinstance(stream, dict):
                        continue
                    udp_info = stream.get("udp")
                    summary = udp_info if isinstance(udp_info, dict) else stream
                    break

            if not isinstance(summary, dict):
                continue

            end_time = self._safe_float(summary.get("end"))
            if end_time is None:
                seconds = self._safe_float(summary.get("seconds"))
                start_time = self._safe_float(summary.get("start")) or 0.0
                end_time = start_time + seconds if seconds is not None else float(index + 1)

            bps = self._safe_float(summary.get("bits_per_second"))
            jitter_ms = self._safe_float(summary.get("jitter_ms"))
            loss_percent = self._safe_float(summary.get("lost_percent"))

            packets = self._safe_int(summary.get("packets"))
            lost_packets = self._safe_int(summary.get("lost_packets"))
            if loss_percent is None and packets and lost_packets is not None:
                loss_percent = lost_packets / packets * 100.0

            series.append(
                {
                    "time_s": round(end_time, 2),
                    "throughput_mbps": round(bps / 1e6, 2) if bps is not None else None,
                    "jitter_ms": round(jitter_ms, 2) if jitter_ms is not None else None,
                    "loss_percent": round(loss_percent, 2) if loss_percent is not None else None,
                }
            )
        return series

    def run_udp_test(self, bandwidth_mbps=10, duration=10, callback=None, test_mode="single"):
        """执行UDP带宽测试

        Args:
            bandwidth_mbps: 目标带宽(Mbps)
            duration: 测试时长(秒)
            callback: 进度回调函数 callback(progress, message)

        Returns:
            dict: 测试结果，包含jitter, loss, latency等指标
        """
        if not self.device_ip:
            return None, "未设置设备IP地址"

        self._cancel_requested = False

        if callback:
            callback(10, f"开始UDP测试，带宽={bandwidth_mbps}Mbps，时长={duration}秒")

        log_manager.info(
            f"[WiFiTest] 开始UDP测试: device={self.device_ip}, bandwidth={bandwidth_mbps}Mbps, "
            f"duration={duration}s"
        )

        try:
            cmd = [
                self.iperf_path,
                "-c",
                self.device_ip,
                "-u",
                "-b",
                f"{bandwidth_mbps}M",
                "-t",
                str(duration),
                "-i",
                "1",
                "-J",
            ]

            wifi_info_before = self.get_wifi_info()

            if callback:
                callback(20, "正在执行iperf3测试...")

            log_manager.info(f"[WiFiTest] 执行命令: {' '.join(cmd)}")

            start_time = time.time()
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            self._current_process = process

            stdout, stderr = process.communicate(timeout=duration + 30)
            elapsed_time = time.time() - start_time

            if self._cancel_requested:
                return None, "测试已取消"

            stdout_text = self._decode_output(stdout).strip()
            stderr_text = self._decode_output(stderr).strip()

            if callback:
                callback(80, "正在解析测试结果...")

            try:
                if not stdout_text:
                    error_msg = "iperf3未返回JSON结果"
                    log_manager.error(error_msg)
                    if stderr_text:
                        log_manager.error(f"[WiFiTest] iperf stderr(前2000字): {stderr_text[:2000]}")
                    return None, error_msg

                result_json = json.loads(stdout_text or "{}")
                if not isinstance(result_json, dict) or "end" not in result_json:
                    error_msg = "iperf3 JSON结果缺少end字段"
                    log_manager.error(error_msg)
                    log_manager.error(f"[WiFiTest] iperf stdout(前2000字): {stdout_text[:2000]}")
                    if stderr_text:
                        log_manager.error(f"[WiFiTest] iperf stderr(前2000字): {stderr_text[:2000]}")
                    return None, error_msg
            except json.JSONDecodeError as e:
                error_msg = f"解析iperf3结果失败: {str(e)}"
                log_manager.error(error_msg)
                if stdout_text:
                    log_manager.error(f"[WiFiTest] iperf stdout(前2000字): {stdout_text[:2000]}")
                if stderr_text:
                    log_manager.error(f"[WiFiTest] iperf stderr(前2000字): {stderr_text[:2000]}")
                return None, error_msg

            end_summary = result_json.get("end", {}) if isinstance(result_json, dict) else {}
            interval_series = self._extract_interval_series(result_json)

            throughput_bps, throughput_source = self._select_metric(end_summary, "bits_per_second")
            jitter_ms, jitter_source = self._select_metric(end_summary, "jitter_ms")
            packets_sent, packets_sent_source = self._select_metric(end_summary, "packets", prefer_order=("sum_sent", "sum", "sum_received"))
            packets_received, packets_received_source = self._select_metric(
                end_summary,
                "packets",
                prefer_order=("sum_received", "sum", "sum_sent"),
            )
            lost_packets, lost_packets_source = self._select_metric(
                end_summary,
                "lost_packets",
                prefer_order=("sum_received", "sum", "sum_sent"),
            )
            loss_percent, loss_source = self._select_metric(
                end_summary,
                "lost_percent",
                prefer_order=("sum_received", "sum", "sum_sent"),
            )

            interval_jitters = []
            for interval in result_json.get("intervals", []) or []:
                for stream in interval.get("streams", []) or []:
                    udp_info = stream.get("udp")
                    if isinstance(udp_info, dict):
                        jitter_value = udp_info.get("jitter_ms")
                        if jitter_value is not None:
                            jitter_value = self._safe_float(jitter_value)
                            if jitter_value is not None:
                                interval_jitters.append(jitter_value)

            if jitter_ms is None and interval_jitters:
                jitter_ms = sum(interval_jitters) / len(interval_jitters)
                jitter_source = "intervals"

            if packets_sent is None:
                packets_sent = 0
            else:
                packets_sent = self._safe_int(packets_sent) or 0

            if packets_received is None:
                packets_received = 0
            else:
                packets_received = self._safe_int(packets_received) or 0

            if lost_packets is None and packets_sent >= packets_received:
                lost_packets = packets_sent - packets_received

            if loss_percent is None and packets_sent > 0:
                if lost_packets is not None:
                    loss_percent = (lost_packets / packets_sent) * 100
                elif packets_received is not None:
                    loss_percent = max(packets_sent - packets_received, 0) / packets_sent * 100

            if throughput_bps is None:
                throughput_bps = 0
            throughput_bps = self._safe_float(throughput_bps) or 0.0
            jitter_ms = self._safe_float(jitter_ms)
            loss_percent = self._safe_float(loss_percent)
            lost_packets = self._safe_int(lost_packets) if lost_packets is not None else None

            wifi_info_after = self.get_wifi_info()
            wifi_info = wifi_info_after if wifi_info_after.get("valid") else wifi_info_before
            ping_stats = self._measure_ping(self.device_ip, count=4)

            ping_avg_latency = ping_stats.get("avg_latency_ms")
            ping_loss_percent = ping_stats.get("loss_percent")

            avg_latency_ms = ping_avg_latency
            latency_source = "ping"
            if avg_latency_ms is None:
                avg_latency_ms = jitter_ms
                latency_source = jitter_source or "iperf"

            test_result = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "test_mode": test_mode,
                "bandwidth_target": bandwidth_mbps,
                "duration": duration,
                "interval_series": interval_series,
                "throughput_mbps": round(throughput_bps / 1e6, 2) if throughput_bps is not None else None,
                "jitter_ms": round(jitter_ms, 2) if jitter_ms is not None else None,
                "loss_percent": round(loss_percent, 2) if loss_percent is not None else None,
                "avg_latency_ms": round(avg_latency_ms, 2) if avg_latency_ms is not None else None,
                "rssi_dbm": wifi_info.get("rssi"),
                "link_speed_mbps": wifi_info.get("link_speed"),
                "rssi_start_dbm": wifi_info_before.get("rssi"),
                "rssi_end_dbm": wifi_info_after.get("rssi"),
                "link_speed_start_mbps": wifi_info_before.get("link_speed"),
                "link_speed_end_mbps": wifi_info_after.get("link_speed"),
                "wifi_interface": wifi_info.get("interface"),
                "wifi_source": wifi_info.get("source"),
                "rssi_source": wifi_info.get("rssi_source"),
                "link_speed_source": wifi_info.get("link_speed_source"),
                "ping_loss_percent": round(ping_loss_percent, 2) if ping_loss_percent is not None else None,
                "packets_sent": packets_sent,
                "packets_received": packets_received,
                "lost_packets": lost_packets,
                "elapsed_time": round(elapsed_time, 2),
                "throughput_source": throughput_source,
                "jitter_source": jitter_source,
                "loss_source": loss_source,
                "latency_source": latency_source,
            }

            self.test_results.append(test_result)

            if callback:
                callback(100, "测试完成")

            throughput_text = (
                f"{test_result['throughput_mbps']:.2f}"
                if test_result["throughput_mbps"] is not None
                else "N/A"
            )
            jitter_text = f"{test_result['jitter_ms']:.2f}" if test_result["jitter_ms"] is not None else "N/A"
            loss_text = f"{test_result['loss_percent']:.2f}" if test_result["loss_percent"] is not None else "N/A"
            latency_text = f"{test_result['avg_latency_ms']:.2f}" if test_result["avg_latency_ms"] is not None else "N/A"
            rssi_text = (
                f"{test_result['rssi_dbm']:.0f}" if test_result["rssi_dbm"] is not None else "N/A"
            )
            speed_text = (
                f"{test_result['link_speed_mbps']:.1f}"
                if test_result["link_speed_mbps"] is not None
                else "N/A"
            )
            ping_loss_text = (
                f"{test_result['ping_loss_percent']:.2f}"
                if test_result["ping_loss_percent"] is not None
                else "N/A"
            )

            log_manager.info(
                f"[WiFiTest] 完成UDP测试: device={self.device_ip}, bandwidth={bandwidth_mbps}Mbps, "
                f"throughput={throughput_text}Mbps({throughput_source}), jitter={jitter_text}ms({jitter_source}), "
                f"loss={loss_text}%({loss_source}), latency={latency_text}ms({latency_source}), "
                f"RSSI={rssi_text}dBm, link_speed={speed_text}Mbps, iface={wifi_info.get('interface')}, "
                f"wifi_source={wifi_info.get('source')}, ping_loss={ping_loss_text}%"
            )

            if (
                test_result["throughput_mbps"] in (None, 0)
                or test_result["jitter_ms"] is None
                or test_result["loss_percent"] is None
                or test_result["avg_latency_ms"] is None
            ):
                log_manager.warning(
                    f"[WiFiTest] 指标解析不完整，建议检查设备端 iperf3 输出或 ping 连通性。"
                    f" end_keys={list(end_summary.keys()) if isinstance(end_summary, dict) else 'N/A'}"
                )
                if stdout_text:
                    log_manager.debug(f"[WiFiTest] iperf stdout(前4000字): {stdout_text[:4000]}")
                if stderr_text:
                    log_manager.debug(f"[WiFiTest] iperf stderr(前4000字): {stderr_text[:4000]}")
                if ping_stats.get("output"):
                    log_manager.debug(f"[WiFiTest] ping output(前4000字): {ping_stats['output'][:4000]}")

            return test_result, "测试成功"

        except subprocess.TimeoutExpired:
            if self._current_process and self._current_process.poll() is None:
                self._current_process.kill()
            error_msg = "iperf3测试超时"
            log_manager.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"UDP测试失败: {str(e)}"
            log_manager.error(error_msg, exc_info=True)
            return None, error_msg
        finally:
            self._current_process = None

    def run_bandwidth_sweep(self, bandwidths=None, duration=10, progress_callback=None):
        """执行多带宽扫描测试

        Args:
            bandwidths: 带宽列表(Mbps)，默认为[5, 10, 20, 30, 40, 50]
            duration: 每个带宽测试的时长(秒)
            progress_callback: 进度回调 callback(current, total, bandwidth, result)

        Returns:
            list: 所有测试结果
        """
        if bandwidths is None:
            bandwidths = [5, 10, 20, 30, 40, 50]

        results = []
        total = len(bandwidths)

        for i, bw in enumerate(bandwidths):
            if self._cancel_requested:
                break

            if progress_callback:
                progress_callback(i, total, bw, None)

            result, msg = self.run_udp_test(bandwidth_mbps=bw, duration=duration, test_mode="multi")

            if result:
                results.append(result)

            if progress_callback:
                progress_callback(i + 1, total, bw, result)

        return results

    def export_to_csv(self, filename=None):
        """导出测试结果到CSV文件

        Args:
            filename: 文件名，默认自动生成

        Returns:
            str: 保存的文件路径
        """
        if not self.test_results:
            return None, "没有可导出的测试结果"

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wifi_perf_test_{timestamp}.csv"

        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

        def _csv_value(value):
            return "" if value is None else value

        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as csvfile:
                fieldnames = [
                    "时间戳",
                    "目标带宽(Mbps)",
                    "测试时长(s)",
                    "实际吞吐量(Mbps)",
                    "抖动(ms)",
                    "丢包率(%)",
                    "平均延迟(ms)",
                    "RSSI(dBm)",
                    "协商速率(Mbps)",
                    "WiFi接口",
                    "RSSI来源",
                    "协商速率来源",
                    "Ping丢包率(%)",
                    "发送数据包",
                    "接收数据包",
                    "丢失数据包",
                    "耗时(s)",
                ]

                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for result in self.test_results:
                    writer.writerow(
                        {
                            "时间戳": result.get("timestamp"),
                            "目标带宽(Mbps)": _csv_value(result.get("bandwidth_target")),
                            "测试时长(s)": _csv_value(result.get("duration")),
                            "实际吞吐量(Mbps)": _csv_value(result.get("throughput_mbps")),
                            "抖动(ms)": _csv_value(result.get("jitter_ms")),
                            "丢包率(%)": _csv_value(result.get("loss_percent")),
                            "平均延迟(ms)": _csv_value(result.get("avg_latency_ms")),
                            "RSSI(dBm)": _csv_value(result.get("rssi_dbm")),
                            "协商速率(Mbps)": _csv_value(result.get("link_speed_mbps")),
                            "WiFi接口": _csv_value(result.get("wifi_interface")),
                            "RSSI来源": _csv_value(result.get("rssi_source")),
                            "协商速率来源": _csv_value(result.get("link_speed_source")),
                            "Ping丢包率(%)": _csv_value(result.get("ping_loss_percent")),
                            "发送数据包": _csv_value(result.get("packets_sent")),
                            "接收数据包": _csv_value(result.get("packets_received")),
                            "丢失数据包": _csv_value(result.get("lost_packets")),
                            "耗时(s)": _csv_value(result.get("elapsed_time")),
                        }
                    )

            log_manager.info(f"[WiFiTest] 测试结果已导出到: {filepath}")
            return filepath, "导出成功"

        except Exception as e:
            error_msg = f"导出CSV失败: {str(e)}"
            log_manager.error(error_msg, exc_info=True)
            return None, error_msg

    def clear_results(self):
        """清空测试结果"""
        self.test_results.clear()
        log_manager.info("[WiFiTest] 测试结果已清空")
