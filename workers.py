# -*- coding: utf-8 -*-
"""
后台任务 worker。

所有耗时设备操作都通过 Qt 信号把结果传回主线程，避免后台线程直接操作 UI。
"""

import os
import time
import traceback

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from log_manager import LogManager


log_manager = LogManager()


class FileTransferWorker(QObject):
    """模型、配置等文件传输后台任务。"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, device_manager, operation_type, **kwargs):
        super().__init__()
        self.device_manager = device_manager
        self.operation_type = operation_type
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):
        try:
            log_manager.info(f"[WORKER] 开始执行 {self.operation_type} 操作")

            if self.operation_type == "push_model":
                self._push_model()
            elif self.operation_type == "push_config":
                self._push_config()
            elif self.operation_type == "delete_model":
                self._delete_model()
            else:
                self.finished.emit(False, f"未知操作类型: {self.operation_type}")

        except Exception as e:
            error_trace = traceback.format_exc()
            log_manager.error(f"[WORKER] {self.operation_type} 操作异常: {e}", exc_info=True)
            self.finished.emit(False, f"{str(e)}\n{error_trace}")

    def _push_model(self):
        model_file = self.kwargs.get("model_file")
        device_ip = self.kwargs.get("device_ip")

        self.progress.emit(10, "正在连接设备...")
        success, msg = self.device_manager.push_model(model_file, device_ip, "SSH")

        if not success:
            self.finished.emit(False, msg)
            return

        self.progress.emit(80, "模型推送成功，正在重启进程...")
        restart_success, restart_msg = self.device_manager.restart_media_process(device_ip)

        self.progress.emit(100, "完成")
        if restart_success:
            self.finished.emit(True, f"{msg}\n✅ multi_media进程已自动重启")
        else:
            self.finished.emit(True, f"{msg}\n⚠️ multi_media重启失败: {restart_msg}")

    def _push_config(self):
        config_file = self.kwargs.get("config_file")
        device_ip = self.kwargs.get("device_ip")

        try:
            self.progress.emit(10, "正在连接设备...")
            success, msg = self.device_manager.push_config(config_file, device_ip)

            if not success:
                self.finished.emit(False, msg)
                return

            self.progress.emit(80, "配置推送成功，正在重启进程...")
            restart_success, restart_msg = self.device_manager.restart_media_process(device_ip)

            self.progress.emit(100, "完成")
            if restart_success:
                self.finished.emit(True, f"{msg}\n✅ multi_media进程已自动重启，新配置已生效")
            else:
                self.finished.emit(True, f"{msg}\n⚠️ multi_media重启失败: {restart_msg}")
        finally:
            if config_file and os.path.exists(config_file):
                try:
                    os.remove(config_file)
                except OSError:
                    log_manager.warning(f"[WORKER] 临时配置文件清理失败: {config_file}")

    def _delete_model(self):
        model_name = self.kwargs.get("model_name")
        device_ip = self.kwargs.get("device_ip")

        self.progress.emit(10, "正在连接设备...")
        self.progress.emit(50, f"正在删除模型 {model_name}...")
        success, msg = self.device_manager.delete_model(model_name, device_ip)

        if success:
            self.progress.emit(100, "完成")
        self.finished.emit(success, msg)


class VideoUploadWorker(QObject):
    """视频上传后台任务。"""

    progress = pyqtSignal(int, float, float)
    finished = pyqtSignal(bool, str)

    def __init__(self, device_manager, video_file, device_ip):
        super().__init__()
        self.device_manager = device_manager
        self.video_file = video_file
        self.device_ip = device_ip
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    @pyqtSlot()
    def run(self):
        def progress_callback(transferred, total):
            if self.cancelled:
                return
            percent = int(transferred / total * 100) if total > 0 else 0
            self.progress.emit(percent, transferred / 1024 / 1024, total / 1024 / 1024)

        try:
            if self.cancelled:
                self.finished.emit(False, "上传已取消")
                return

            success, msg = self.device_manager.push_video(
                self.video_file,
                self.device_ip,
                progress_callback,
            )
            if self.cancelled:
                self.finished.emit(False, "上传已取消")
            else:
                self.finished.emit(success, msg)
        except Exception as e:
            self.finished.emit(False, f"上传异常: {str(e)}")


class LogDownloadWorker(QObject):
    """设备日志下载后台任务，支持取消、残留清理和速度上报。"""

    progress = pyqtSignal(int, float, float, float)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, device_ip, remote_path, local_path):
        super().__init__()
        self.device_ip = device_ip
        self.remote_path = remote_path
        self.local_path = local_path
        self.cancelled = False
        self._ssh = None
        self._sftp = None
        self._remote_file = None

    def cancel(self):
        self.cancelled = True
        for handle in (self._remote_file, self._sftp, self._ssh):
            try:
                if handle:
                    handle.close()
            except Exception:
                pass

    @pyqtSlot()
    def run(self):
        success = False
        try:
            import paramiko

            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(self.device_ip, port=22, username="root", password="", timeout=10)
            self._sftp = self._ssh.open_sftp()

            total = self._sftp.stat(self.remote_path).st_size
            os.makedirs(os.path.dirname(self.local_path), exist_ok=True)

            transferred = 0
            start_time = time.monotonic()
            last_emit = start_time
            last_bytes = 0

            with self._sftp.open(self.remote_path, "rb") as remote_file, open(self.local_path, "wb") as local_file:
                self._remote_file = remote_file

                while True:
                    if self.cancelled:
                        raise InterruptedError("下载已取消")

                    chunk = remote_file.read(256 * 1024)
                    if not chunk:
                        break

                    local_file.write(chunk)
                    transferred += len(chunk)

                    now = time.monotonic()
                    if now - last_emit >= 0.2 or transferred == total:
                        elapsed = max(now - last_emit, 0.001)
                        speed = (transferred - last_bytes) / elapsed
                        percent = int(transferred / total * 100) if total else 0
                        self.progress.emit(percent, transferred / 1024 / 1024, total / 1024 / 1024, speed / 1024 / 1024)
                        last_emit = now
                        last_bytes = transferred

            success = True
            avg_speed = transferred / max(time.monotonic() - start_time, 0.001)
            self.progress.emit(100, transferred / 1024 / 1024, total / 1024 / 1024, avg_speed / 1024 / 1024)
            self.finished.emit(True, "下载完成", self.local_path)

        except Exception as e:
            if self.cancelled:
                self._cleanup_partial()
                self.finished.emit(False, "下载已取消", "")
            else:
                log_manager.error(f"[LOG] 下载日志失败: {str(e)}", exc_info=True)
                self._cleanup_partial()
                self.finished.emit(False, f"下载日志失败: {str(e)}", "")
        finally:
            self._remote_file = None
            for handle in (self._sftp, self._ssh):
                try:
                    if handle:
                        handle.close()
                except Exception:
                    pass
            self._sftp = None
            self._ssh = None

            if not success and not self.cancelled:
                self._cleanup_partial()

    def _cleanup_partial(self):
        try:
            if self.local_path and os.path.exists(self.local_path):
                os.remove(self.local_path)
        except OSError as e:
            log_manager.warning(f"[LOG] 清理未完成日志文件失败: {self.local_path}, {e}")


class WiFiPerfTestWorker(QObject):
    """WiFi 性能测试后台任务。"""

    progress = pyqtSignal(int, str)
    result_ready = pyqtSignal(dict)
    finished = pyqtSignal(bool, str)

    @staticmethod
    def _fmt(value, digits=2, suffix=""):
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.{digits}f}{suffix}"
        except (TypeError, ValueError):
            return str(value)

    def __init__(self, tester, mode, duration, bandwidth=None, bandwidths=None):
        super().__init__()
        self.tester = tester
        self.mode = mode
        self.duration = duration
        self.bandwidth = bandwidth
        self.bandwidths = bandwidths or []
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        cancel = getattr(self.tester, "cancel_current_test", None)
        if cancel:
            cancel()

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit(5, "正在启动iperf3服务器...")
            success, msg = self.tester.start_iperf_server()
            if not success:
                self.finished.emit(False, f"启动服务器失败: {msg}")
                return

            if self.cancelled:
                self.finished.emit(False, "测试已取消")
                return

            if self.mode == "single":
                self._run_single()
            else:
                self._run_multi()

        except Exception as e:
            log_manager.error(f"WiFi测试异常: {str(e)}", exc_info=True)
            self.finished.emit(False, f"测试异常: {str(e)}")
        finally:
            self.tester.stop_iperf_server()

    def _run_single(self):
        def progress_callback(progress, message):
            if not self.cancelled:
                self.progress.emit(progress, message)

        result, msg = self.tester.run_udp_test(
            bandwidth_mbps=self.bandwidth,
            duration=self.duration,
            callback=progress_callback,
        )

        if self.cancelled:
            self.finished.emit(False, "测试已取消")
        elif result:
            self.result_ready.emit(result)
            self.progress.emit(
                100,
                "测试完成: "
                f"带宽={self._fmt(result.get('bandwidth_target'), 0, 'Mbps')}, "
                f"吞吐量={self._fmt(result.get('throughput_mbps'), 2, 'Mbps')}, "
                f"RSSI={self._fmt(result.get('rssi_dbm'), 0, 'dBm')}, "
                f"协商速率={self._fmt(result.get('link_speed_mbps'), 1, 'Mbps')}",
            )
            self.finished.emit(
                True,
                f"测试完成: 吞吐量={self._fmt(result.get('throughput_mbps'), 2, 'Mbps')}, "
                f"丢包={self._fmt(result.get('loss_percent'), 2, '%')}",
            )
        else:
            self.finished.emit(False, msg)

    def _run_multi(self):
        total = len(self.bandwidths)

        def progress_callback(current, total_count, bandwidth, result):
            if self.cancelled:
                return

            progress = int((current / total_count) * 100) if total_count else 0
            if current < total_count:
                self.progress.emit(progress, f"测试进度: {current}/{total_count} (带宽={bandwidth}Mbps)")
            else:
                if result:
                    self.progress.emit(
                        100,
                        "测试完成: "
                        f"带宽={self._fmt(result.get('bandwidth_target'), 0, 'Mbps')}, "
                        f"吞吐量={self._fmt(result.get('throughput_mbps'), 2, 'Mbps')}, "
                        f"RSSI={self._fmt(result.get('rssi_dbm'), 0, 'dBm')}, "
                        f"协商速率={self._fmt(result.get('link_speed_mbps'), 1, 'Mbps')}",
                    )
                else:
                    self.progress.emit(100, "测试完成")

            if result:
                self.result_ready.emit(result)

        results = self.tester.run_bandwidth_sweep(
            bandwidths=self.bandwidths,
            duration=self.duration,
            progress_callback=progress_callback,
        )

        if self.cancelled:
            self.finished.emit(False, "测试已取消")
        elif results:
            self.finished.emit(True, f"扫描完成: 共{len(results)}个测试点")
        else:
            self.finished.emit(False, "测试失败")


class PerformanceStartWorker(QObject):
    """性能监控启动后台任务。"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, performance_monitor, device_ip, ddr_freq, interval):
        super().__init__()
        self.performance_monitor = performance_monitor
        self.device_ip = device_ip
        self.ddr_freq = ddr_freq
        self.interval = interval

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit(10, "正在建立SSH连接...")
            self.performance_monitor.start_monitoring(
                self.device_ip,
                self.ddr_freq,
                self.interval,
                progress_callback=lambda percent, message: self.progress.emit(percent, message),
            )
            self.progress.emit(100, "监控已启动")
            self.finished.emit(True, "success")
        except Exception as e:
            log_manager.error(f"[PERF] 启动性能监控失败: {str(e)}", exc_info=True)
            self.finished.emit(False, str(e))


class WiFiReconnectWorker(QObject):
    """启动时自动 WiFi 重连后台任务。"""

    finished = pyqtSignal(bool, str, str, str, str)

    def __init__(self, device_manager, device_ip, wifi_ssid, wifi_password, rtsp_0, rtsp_1):
        super().__init__()
        self.device_manager = device_manager
        self.device_ip = device_ip
        self.wifi_ssid = wifi_ssid
        self.wifi_password = wifi_password
        self.rtsp_0 = rtsp_0
        self.rtsp_1 = rtsp_1

    @pyqtSlot()
    def run(self):
        try:
            from smart_device_manager import SmartDeviceManager

            log_manager.info(f"[AUTO] 正在通过ADB配置WiFi: {self.wifi_ssid}")
            smart_manager = SmartDeviceManager()
            success, msg, ip, new_rtsp_0, new_rtsp_1 = smart_manager.full_auto_setup(
                self.wifi_ssid,
                self.wifi_password,
            )

            if not success or not ip:
                log_manager.warning(f"[AUTO] WiFi重连失败: {msg}")
                self.finished.emit(False, self.device_ip, self.rtsp_0, self.rtsp_1, f"WiFi重连失败: {msg}")
                return

            log_manager.info(f"[AUTO] WiFi重连成功: {ip}")
            log_manager.info(f"[AUTO] 正在建立SSH连接到 {ip}...")
            ssh_success, ssh_msg = self.device_manager.connect_ssh(ip)

            if ssh_success:
                log_manager.info(f"[AUTO] SSH连接成功: {ssh_msg}")
                self.finished.emit(
                    True,
                    ip,
                    new_rtsp_0 or self.rtsp_0,
                    new_rtsp_1 or self.rtsp_1,
                    "WiFi重连成功",
                )
            else:
                log_manager.error(f"[AUTO] SSH连接失败: {ssh_msg}")
                self.finished.emit(False, ip, self.rtsp_0, self.rtsp_1, f"WiFi重连成功但SSH连接失败: {ssh_msg}")

        except Exception as e:
            log_manager.error(f"[AUTO] WiFi重连异常: {str(e)}", exc_info=True)
            self.finished.emit(False, self.device_ip, self.rtsp_0, self.rtsp_1, str(e))


class AutoConnectWorker(QObject):
    """启动时自动连接设备的后台任务。"""

    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str, str, str)

    def __init__(self, device_manager, config):
        super().__init__()
        self.device_manager = device_manager
        self.config = config or {}

    def _run_wifi_setup(self, fallback_ip, rtsp_0, rtsp_1):
        from smart_device_manager import SmartDeviceManager

        wifi_ssid = self.config.get('wifi_ssid', '')
        wifi_password = self.config.get('wifi_password', '')
        if not wifi_ssid or not wifi_password:
            return False, fallback_ip, rtsp_0, rtsp_1, "缺少WiFi配置信息，无法自动重连"

        self.status.emit("正在通过ADB重新配置WiFi...")
        log_manager.info("[AUTO] 先通过ADB配置WiFi，入网后再启动SSH服务")
        smart_manager = SmartDeviceManager()
        success, msg, ip, new_rtsp_0, new_rtsp_1 = smart_manager.full_auto_setup(
            wifi_ssid,
            wifi_password,
        )
        if not success or not ip:
            return False, fallback_ip, rtsp_0, rtsp_1, f"WiFi重连失败: {msg}"

        self.status.emit(f"正在连接设备: {ip}...")
        ssh_success, ssh_msg = self.device_manager.connect_ssh(ip)
        if not ssh_success:
            return False, ip, rtsp_0, rtsp_1, f"WiFi重连成功但SSH连接失败: {ssh_msg}"

        return True, ip, new_rtsp_0 or rtsp_0, new_rtsp_1 or rtsp_1, "WiFi重连成功"

    @pyqtSlot()
    def run(self):
        try:
            device_ip = self.config.get('device_ip')
            rtsp_0 = self.config.get('rtsp_0')
            rtsp_1 = self.config.get('rtsp_1')

            if not device_ip:
                self.finished.emit(False, "", "", "", "配置文件中没有设备IP")
                return

            self.status.emit("正在检测设备状态...")
            log_manager.info(f"[AUTO] 检测到上次配置的设备: {device_ip}，开始后台连接")

            current_ip = self.device_manager.get_current_device_ip_via_adb()
            if current_ip:
                log_manager.info(f"[AUTO] ADB检测到设备当前IP: {current_ip}")
                if current_ip != device_ip:
                    log_manager.warning(f"[AUTO] IP不一致: 配置IP={device_ip}, 当前IP={current_ip}")
                    self.status.emit(f"检测到新IP，正在连接设备: {current_ip}...")
                    ssh_success, ssh_msg = self.device_manager.connect_ssh(current_ip)
                    if ssh_success:
                        self.finished.emit(
                            True,
                            current_ip,
                            f"rtsp://{current_ip}/live/0",
                            f"rtsp://{current_ip}/live/1",
                            "检测到设备IP变化并自动连接成功",
                        )
                        return
                    log_manager.warning(f"[AUTO] 当前IP直连失败: {ssh_msg}，尝试WiFi重连")
                    success, ip, new_rtsp_0, new_rtsp_1, msg = self._run_wifi_setup(
                        device_ip,
                        rtsp_0,
                        rtsp_1,
                    )
                    self.finished.emit(success, ip, new_rtsp_0 or "", new_rtsp_1 or "", msg)
                    return
            else:
                log_manager.info("[AUTO] 未能通过ADB获取设备IP，将尝试配置IP直连")

            target_ip = current_ip or device_ip
            self.status.emit(f"正在连接设备: {target_ip}...")
            # 旧IP直连失败时先走配网流程，不急着对可能已经失效的地址启动sshd。
            ssh_success, ssh_msg = self.device_manager.connect_ssh(
                target_ip,
                auto_start_ssh=bool(current_ip),
            )
            if ssh_success:
                self.finished.emit(True, target_ip, rtsp_0 or "", rtsp_1 or "", "SSH连接成功")
                return

            log_manager.warning(f"[AUTO] SSH直连失败: {ssh_msg}")
            success, ip, new_rtsp_0, new_rtsp_1, msg = self._run_wifi_setup(
                target_ip,
                rtsp_0,
                rtsp_1,
            )
            if success:
                self.finished.emit(True, ip, new_rtsp_0 or "", new_rtsp_1 or "", msg)
            else:
                self.finished.emit(False, ip, new_rtsp_0 or "", new_rtsp_1 or "", f"{ssh_msg}；{msg}")

        except Exception as e:
            log_manager.error(f"[AUTO] 自动连接后台任务异常: {str(e)}", exc_info=True)
            self.finished.emit(False, self.config.get('device_ip', ''), "", "", str(e))
