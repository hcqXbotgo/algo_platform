# -*- coding: utf-8 -*-
"""
性能监控模块
功能：监控NPU、CPU、内存占用和DDR带宽
注意：DDR带宽通过实时阻塞命令读取，已移除旧的轮询获取方式
"""

import threading
import time
import os
import re
import subprocess
from datetime import datetime

from device_manager import DeviceManager, connect_ssh_with_retry
from device_resources import DEVICE_DETECTION_COMMAND, DEVICE_RESOURCE_PROFILES


class PerformanceMonitor:
    """性能监控器"""

    FALCON2_DDR_FREQ = 3733

    def __init__(self, serial_manager=None):
        self.monitoring = False
        self.ssh_client = None
        self.ssh_username = 'root'
        self.ssh_password = ''
        self.ssh_port = 22
        self.adb_device_id = None
        self.connection_mode = None
        self.device_ip = None
        self.ddr_freq = 1848
        self.memory_source = None
        self.npu_source = None
        self.ddr_source = None
        self.device_profile = None
        self.extra_memory_source = None
        self.serial_manager = serial_manager
        self.serial_port = None
        self.serial_baudrate = 115200
        self.history_data = {
            'timestamps': [],
            'npu_core0': [],  # NPU Core0占用率
            'npu_core1': [],  # NPU Core1占用率
            'npu_load': [],   # NPU综合占用率
            'cpu_usage': [],
            'memory_used_mb': [],  # 内存实际使用量(MB)
            'memory_total_mb': [], # 内存总量(MB)
            'memory_usage': [],    # 内存占用率(%)
            'mmz_used_mb': [],     # Falcon2 MMZ媒体内存使用量(MB)
            'mmz_total_mb': [],    # Falcon2 MMZ媒体内存总量(MB)
            'mmz_usage': [],       # Falcon2 MMZ媒体内存占用率(%)
            'mal_used_mb': [],     # Ambarella MAL已分配内存(MB)
            'mal_total_mb': [],    # Ambarella MAL总内存（若设备提供）
            'mal_usage': [],       # Ambarella MAL占用率（若设备提供）
            'ddr_total': [],       # DDR总带宽
            'ddr_modules': []      # 各模块带宽: {'cpu': x, 'isp': y, 'npu': z, ...}
        }
        # 完整历史数据（用于导出，不限制长度）
        self.full_history_data = {
            'timestamps': [],
            'npu_core0': [],
            'npu_core1': [],
            'npu_load': [],
            'cpu_usage': [],
            'memory_used_mb': [],
            'memory_total_mb': [],
            'memory_usage': [],
            'mmz_used_mb': [],
            'mmz_total_mb': [],
            'mmz_usage': [],
            'mal_used_mb': [],
            'mal_total_mb': [],
            'mal_usage': [],
            'ddr_total': [],
            'ddr_modules': []
        }
        self.latest_data = {}
        self.monitor_thread = None
        self.local_tool_path = None  # 可选的自定义 DDR 工具路径
        self._stop_event = threading.Event()

        # DDR监控相关
        self.ddr_process = None  # 阻塞命令的SSH通道
        self.ddr_reader_thread = None  # 读取输出的线程
        self.ddr_sample_thread = None  # 单次DDR采样线程，避免阻塞主监控循环
        self._ddr_next_retry_at = 0.0
        self._ddr_failure_count = 0
        self.latest_ddr_data = {}  # 最新解析的DDR数据
        self.ddr_status = "未启动"
        self.ddr_last_error = ""
        self.ddr_output_tail = []

        # NPU监控相关
        self.latest_npu_data = {'core0': 0.0, 'core1': 0.0, 'avg': 0.0, 'core_count': 2}
        self._npu_smoothed_load = None

    def configure_serial(self, port, baudrate=115200):
        """Configure the serial endpoint used by serial-backed collectors."""
        self.serial_port = str(port or "").strip() or None
        try:
            self.serial_baudrate = int(baudrate or 115200)
        except (TypeError, ValueError):
            self.serial_baudrate = 115200

    def set_tool_path(self, local_path):
        """设置本地工具文件路径"""
        if os.path.exists(local_path):
            self.local_tool_path = local_path
            return True, f"工具路径已设置: {local_path}"
        else:
            return False, f"工具文件不存在: {local_path}"

    def _get_fallback_tool_path(self):
        """获取随上位机一起打包的 DDR 工具路径。"""
        ddr = self._get_ddr_spec()
        if not ddr or not ddr.get("local_path"):
            return None
        bundled_tool = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            *ddr["local_path"].split("/"),
        )
        if os.path.exists(bundled_tool):
            return bundled_tool
        return None

    def _resolve_local_tool_path(self):
        """解析可用的本地 DDR 工具路径。"""
        if self.local_tool_path and os.path.exists(self.local_tool_path):
            return self.local_tool_path

        fallback_tool = self._get_fallback_tool_path()
        if fallback_tool:
            return fallback_tool

        return None

    def _get_remote_tool_path(self):
        """获取当前设备配置对应的板端 DDR 工具路径。"""
        ddr = self._get_ddr_spec()
        return ddr.get("remote_path") if ddr else None

    def _get_usb_adb_device_id(self):
        if self.connection_mode == "ssh":
            return None, "SSH模式已选择，跳过ADB探测"
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
            )
        except Exception as e:
            return None, str(e)

        if result.returncode != 0:
            return None, (result.stderr or result.stdout or "").strip()
        for line in result.stdout.strip().splitlines()[1:]:
            if "\tdevice" in line:
                device_id = line.split("\t", 1)[0].strip()
                if device_id:
                    return device_id, "OK"
        return None, "未检测到USB ADB设备"

    def _run_adb_shell_command(self, command, timeout=15):
        if not self.adb_device_id:
            return False, "ADB未连接"
        try:
            result = subprocess.run(
                ["adb", "-s", self.adb_device_id, "shell", command],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout,
            )
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode == 0:
                return True, output
            return False, error or output or f"返回码 {result.returncode}"
        except Exception as e:
            return False, str(e)

    def start_monitoring(self, device_ip, ddr_freq=1848, interval=2, progress_callback=None):
        """开始监控

        Args:
            device_ip: 设备IP地址
            ddr_freq: DDR频率(MHz)
            interval: 采样间隔(秒)
            progress_callback: 进度回调函数，接收(百分比, 消息)参数
        """
        self.device_ip = device_ip
        self.ddr_freq = ddr_freq
        self.monitoring = True
        self._stop_event.clear()
        self.ddr_sample_thread = None
        self._ddr_next_retry_at = 0.0
        self._ddr_failure_count = 0
        self.latest_ddr_data = {}
        self.ddr_status = "初始化中"
        self.ddr_last_error = ""
        self.ddr_output_tail = []
        self.memory_source = None
        self.npu_source = None
        self.ddr_source = None
        self.device_profile = None
        self.extra_memory_source = None
        self._npu_smoothed_load = None

        # 建立连接：USB ADB 优先，ADB 不可用再回退 SSH。
        try:
            self.adb_device_id, adb_msg = self._get_usb_adb_device_id()
            if self.adb_device_id:
                self.connection_mode = "adb"
                self.ssh_client = None
                if progress_callback:
                    progress_callback(40, f"ADB连接成功: {self.adb_device_id}")
                print(f"[性能监控] ADB连接成功: {self.adb_device_id}")
            else:
                self.connection_mode = "ssh"
                if progress_callback:
                    progress_callback(20, "正在建立SSH连接...")
                print(f"[性能监控] ADB不可用({adb_msg})，正在连接设备 {device_ip} 的SSH...")

                self.ssh_client, ssh_success, ssh_msg = connect_ssh_with_retry(
                    device_ip,
                    username=self.ssh_username,
                    password=self.ssh_password,
                    port=self.ssh_port,
                )
                if not ssh_success:
                    raise Exception(f"SSH连接失败（不依赖ADB）: {ssh_msg}")

                if progress_callback:
                    progress_callback(40, "SSH连接成功")
                print(f"[性能监控] SSH连接成功")
        except Exception as e:
            self.monitoring = False
            raise Exception(f"设备连接失败: {str(e)}")
        # 清空历史数据
        self.history_data = {
            'timestamps': [],
            'npu_core0': [],  # NPU Core0占用率
            'npu_core1': [],  # NPU Core1占用率
            'npu_load': [],   # NPU综合占用率
            'cpu_usage': [],
            'memory_used_mb': [],  # 内存实际使用量(MB)
            'memory_total_mb': [], # 内存总量(MB)
            'memory_usage': [],    # 内存占用率(%)
            'mmz_used_mb': [],     # Falcon2 MMZ媒体内存使用量(MB)
            'mmz_total_mb': [],    # Falcon2 MMZ媒体内存总量(MB)
            'mmz_usage': [],       # Falcon2 MMZ媒体内存占用率(%)
            'mal_used_mb': [],
            'mal_total_mb': [],
            'mal_usage': [],
            'ddr_total': [],       # DDR总带宽
            'ddr_modules': []      # 各模块带宽: {'cpu': x, 'isp': y, 'npu': z, ...}
        }

        # 清空完整历史数据
        self.full_history_data = {
            'timestamps': [],
            'npu_core0': [],
            'npu_core1': [],
            'npu_load': [],
            'cpu_usage': [],
            'memory_used_mb': [],
            'memory_total_mb': [],
            'memory_usage': [],
            'mmz_used_mb': [],
            'mmz_total_mb': [],
            'mmz_usage': [],
            'mal_used_mb': [],
            'mal_total_mb': [],
            'mal_usage': [],
            'ddr_total': [],
            'ddr_modules': []
        }

        # 检查DDR采集方式并启动DDR监控。当前函数运行在后台 worker 中，可以同步等待结果。
        if progress_callback:
            progress_callback(50, "检查DDR采集方式...")

        def ddr_progress(percent, message):
            if progress_callback:
                progress_callback(50 + int(percent * 0.3), message)

        ddr_tool_available = self._ensure_tool_available(ddr_progress)
        if ddr_tool_available and self._uses_polled_ddr():
            self.ddr_status = "等待采样"
            print(f"[性能监控] {self.device_profile} DDR单次采样已启用")
            if progress_callback:
                progress_callback(90, "DDR单次采样已就绪")
        elif ddr_tool_available:
            if progress_callback:
                progress_callback(85, "启动DDR监控...")
            if self._start_ddr_monitoring():
                if self._wait_for_ddr_initial_state(timeout=2.0):
                    if progress_callback:
                        progress_callback(90, "DDR监控已启动，等待采样数据...")
                elif progress_callback:
                    msg = self.ddr_last_error or self.ddr_status
                    progress_callback(90, f"DDR监控异常: {msg}")
            else:
                msg = self.ddr_last_error or "未知错误"
                print(f"[性能监控] 警告: DDR监控启动失败: {msg}")
                if progress_callback:
                    progress_callback(90, f"DDR监控未启动: {msg}")
        else:
            ddr = self._get_ddr_spec()
            if ddr and ddr.get("transport") == "serial":
                self.ddr_status = "等待串口重连"
                print(f"[性能监控] DDR串口暂不可用，将在监控循环中重试: {self.ddr_last_error}")
                if progress_callback:
                    progress_callback(90, "DDR串口暂不可用，启动后将自动重试")
            else:
                self.ddr_status = "工具不可用"
                print("[性能监控] 警告: DDR工具不可用，将跳过DDR监控")
                if progress_callback:
                    progress_callback(90, "DDR工具不可用，跳过DDR监控")

        # 启动监控线程
        if progress_callback:
            progress_callback(92, "启动主监控线程...")

        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,))
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

        if progress_callback:
            progress_callback(100, "监控已启动！")

        print(f"[性能监控] 监控线程已启动")

    def _wait_for_ddr_initial_state(self, timeout=2.0):
        """等待DDR工具给出第一批数据或快速失败。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ddr_status == "运行中":
                return True
            if self.ddr_status in ("异常", "已退出"):
                return False
            time.sleep(0.1)
        return True

    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        self._stop_event.set()

        profile = DEVICE_RESOURCE_PROFILES.get(self.device_profile, {})
        ddr_spec = profile.get("ddr") or {}
        uses_serial_ddr = (
            ddr_spec.get("transport") == "serial"
            or self.ddr_source == "ambarella_serial"
        )

        # 停止DDR监控进程
        if self.ddr_process:
            try:
                if self.connection_mode == "adb" and hasattr(self.ddr_process, "terminate"):
                    self.ddr_process.terminate()
                    try:
                        self.ddr_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.ddr_process.kill()
                else:
                    self.ddr_process.close()
                print("[DDR] 已停止DDR监控进程")
            except:
                pass
            self.ddr_process = None

        stop_command = self._build_ddr_stop_command()
        if stop_command:
            self._execute_command(stop_command)
        self.ddr_status = "已停止"

        # 等待读取线程结束
        if self.ddr_reader_thread:
            self.ddr_reader_thread.join(timeout=3)
            self.ddr_reader_thread = None

        # 停止主监控线程
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

        # 单次串口采样拥有独立线程；取消其当前命令后再释放串口。
        if self.ddr_sample_thread:
            sample_thread = self.ddr_sample_thread
            sample_thread.join(timeout=2)
            if sample_thread.is_alive():
                print("[DDR] 串口采样线程仍在退出，保留线程引用避免重复启动")
            else:
                self.ddr_sample_thread = None

        # 串口采样可能仍在 execute_command 中，必须在线程停止后再关闭。
        # 否则停止后遗留的 RTOS 会话会影响下一次监控启动。
        if uses_serial_ddr and self.serial_manager is not None:
            was_connected = self.serial_manager.is_connected
            self.serial_manager.disconnect()
            if was_connected:
                print("[DDR] 已断开DDR采集串口")

        # 关闭SSH连接
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None

    def _set_ddr_error(self, message):
        self.ddr_status = "异常"
        self.ddr_last_error = message

    def _write_ddr_serial_diagnostic(self, reason, output):
        """Persist full serial responses that need parser investigation."""
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "ddr_serial_diagnostics.log")
            mode = "w" if os.path.exists(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024 else "a"
            with open(log_path, mode, encoding="utf-8", errors="replace") as log_file:
                log_file.write(
                    f"\n===== {datetime.now().isoformat(timespec='seconds')} | {reason} =====\n"
                )
                log_file.write(str(output or "<empty>"))
                log_file.write("\n===== END =====\n")
            return log_path
        except Exception as exc:
            print(f"[DDR] 写入串口诊断日志失败: {exc}")
            return None

    def _get_ddr_spec(self):
        if self.device_profile:
            return DEVICE_RESOURCE_PROFILES[self.device_profile].get("ddr")
        if self.ddr_source:
            for profile in DEVICE_RESOURCE_PROFILES.values():
                ddr = profile.get("ddr")
                if ddr and ddr.get("source") == self.ddr_source:
                    return ddr
        return DEVICE_RESOURCE_PROFILES[self._detect_device_profile()].get("ddr")

    def _build_ddr_command(self):
        ddr = self._get_ddr_spec()
        if not ddr:
            return "true"
        if ddr.get("transport") == "serial":
            return ddr["command"]
        remote_path = ddr["remote_path"]
        tool_dir, _, tool_name = remote_path.rpartition("/")
        return ddr["command"].format(
            freq=self.FALCON2_DDR_FREQ if ddr["source"] == "vssdk" else self.ddr_freq,
            tool_dir=tool_dir or "/userdata",
            tool_name=tool_name,
        )

    def _build_ddr_stop_command(self):
        ddr = self._get_ddr_spec()
        if ddr:
            return ddr.get("stop_command")
        return None

    def _uses_polled_ddr(self):
        ddr = self._get_ddr_spec()
        return bool(ddr and ddr.get("mode") == "poll")

    def _build_adb_ddr_args(self, command):
        args = ["adb", "-s", self.adb_device_id, "shell"]
        if self.ddr_source == "vssdk":
            args.append("-tt")
        args.append(command)
        return args

    def _ensure_serial_available(self):
        if self.serial_manager is None:
            self._set_ddr_error("未初始化串口管理器")
            return False
        ddr = self._get_ddr_spec() or {}
        connect_attempts = max(1, int(ddr.get("connect_attempts", 3)))
        sync_attempts = max(1, int(ddr.get("sync_attempts", 3)))
        last_error = "未知串口错误"

        def synchronize_console():
            sync_error = "RTOS控制台未返回提示符"
            for sync_attempt in range(1, sync_attempts + 1):
                if self._stop_event.is_set():
                    return False, "监控已停止"
                synchronized, sync_message = self.serial_manager.execute_command(
                    "",
                    timeout=float(ddr.get("sync_timeout", 2.0)),
                    completion_pattern=ddr.get("completion_pattern"),
                    cancel_event=self._stop_event,
                )
                if synchronized:
                    self.ddr_last_error = ""
                    return True, ""
                sync_error = sync_message
                if sync_attempt < sync_attempts:
                    time.sleep(0.2)
            return False, sync_error

        # 端口打开不代表 RTOS 控制台仍处于可用状态。先同步；若会话已失效，
        # 主动关闭后走下面的重连流程，避免必须在串口终端手工断开重连。
        if self.serial_manager.is_connected:
            synchronized, last_error = synchronize_console()
            if synchronized:
                return True
            if not self._stop_event.is_set():
                print(
                    f"[DDR] 已有串口会话不可用（{sync_attempts}次同步失败），"
                    f"准备重新连接: {self._short_serial_error(last_error)}"
                )
            self.serial_manager.disconnect()

        if not self.serial_port:
            self._set_ddr_error("未配置DDR采集串口，请先在串口终端中选择端口")
            return False

        for connect_attempt in range(1, connect_attempts + 1):
            success, message = self.serial_manager.connect(
                self.serial_port,
                self.serial_baudrate,
            )
            if not success:
                last_error = message
                if not self._stop_event.is_set():
                    print(
                        f"[DDR] 串口连接尝试 {connect_attempt}/{connect_attempts} 失败: "
                        f"{self._short_serial_error(message)}"
                    )
                if connect_attempt < connect_attempts:
                    time.sleep(0.5)
                continue

            time.sleep(float(ddr.get("open_delay", 0.5)))
            synchronized, last_error = synchronize_console()
            if synchronized:
                print(f"[DDR] 串口已连接并同步: {self.serial_port} @ {self.serial_baudrate}")
                return True
            if not self._stop_event.is_set():
                print(
                    f"[DDR] 控制台同步失败（{sync_attempts}次），"
                    f"{self._short_serial_error(last_error)}"
                )
            self.serial_manager.disconnect()
            if connect_attempt < connect_attempts:
                time.sleep(0.5)

        self._set_ddr_error(f"串口自动连接失败: {last_error}")
        return False

    @staticmethod
    def _short_serial_error(message, limit=180):
        """Keep serial diagnostics from flooding the monitoring console."""
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(message or ""))
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if len(text) > limit:
            return text[:limit] + "..."
        return text or "未知串口错误"

    def _sample_polled_ddr(self):
        """Run one complete DDR sample using the profile's configured transport."""
        ddr = self._get_ddr_spec()
        if not ddr:
            self._set_ddr_error("当前设备未配置DDR采集方式")
            return False
        command = self._build_ddr_command()
        try:
            if ddr.get("transport") == "serial":
                if not self._ensure_serial_available():
                    return False
                success, output = self.serial_manager.execute_command(
                    command,
                    timeout=float(ddr.get("timeout", 5.0)),
                    idle_timeout=float(ddr.get("idle_timeout", 0.3)),
                    minimum_wait=float(ddr.get("minimum_wait", 0.0)),
                    completion_markers=ddr.get("completion_markers"),
                    completion_pattern=ddr.get("completion_pattern"),
                    cancel_event=self._stop_event,
                )
                if not success:
                    self._set_ddr_error(output)
                    if not self._stop_event.is_set():
                        print(f"[DDR] 串口采样未完整结束: {self._short_serial_error(output)}")
                    self._write_ddr_serial_diagnostic("串口命令未完整结束", output)
                    self.serial_manager.disconnect()
                    return False
            elif self.connection_mode == "adb":
                creationflags = (
                    subprocess.CREATE_NO_WINDOW
                    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                )
                result = subprocess.run(
                    self._build_adb_ddr_args(command),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=8,
                    creationflags=creationflags,
                )
                output = "\n".join(part for part in (result.stdout, result.stderr) if part)
                if result.returncode != 0:
                    self._set_ddr_error(output.strip() or f"ADB返回码 {result.returncode}")
                    return False
            else:
                output = self._execute_command(command)

            parser = ddr.get("parser")
            if parser:
                sample_data = parser(output) or {}
            else:
                sample_data = {}
                line_parser = ddr.get("line_parser")
                for line in output.splitlines():
                    parsed = line_parser(line) if line_parser else None
                    if parsed:
                        sample_data.update(parsed)

            required_keys = tuple(ddr.get("required_keys", ("total",)))
            missing_keys = [key for key in required_keys if key not in sample_data]
            if missing_keys:
                diagnostic_path = None
                if ddr.get("transport") == "serial":
                    diagnostic_path = self._write_ddr_serial_diagnostic(
                        f"解析缺少字段: {missing_keys}",
                        output,
                    )
                output_tail = " | ".join(
                    line.strip() for line in output.splitlines() if line.strip()
                )
                if len(output_tail) > 800:
                    output_tail = output_tail[-800:]
                error_message = "DDR单次采样未返回有效带宽数据"
                if diagnostic_path:
                    error_message += f"（原始回显已保存: {diagnostic_path}）"
                self._set_ddr_error(error_message)
                if not self._stop_event.is_set():
                    print(
                        f"[DDR] 单次采样缺少字段 {missing_keys}，"
                        f"回显摘要: {self._short_serial_error(output_tail, 240)}"
                    )
                return False

            self.latest_ddr_data = sample_data
            self.ddr_status = "运行中"
            self.ddr_last_error = ""
            module_text = ""
            if ddr.get("source") == "ambarella_serial":
                module_text = (
                    f", CPU:{sample_data.get('cpu', 0):.2f} MB/s"
                    f", DSP:{sample_data.get('dsp', 0):.2f} MB/s"
                    f", PERI:{sample_data.get('peri', 0):.2f} MB/s"
                    f", NVPORC:{sample_data.get('nvporc', 0):.2f} MB/s"
                    f", NVP:{sample_data.get('nvp', 0):.2f} MB/s"
                    f", 其他:{sample_data.get('unattributed', 0):.2f} MB/s"
                )
                if not sample_data.get("component_consistent", True):
                    self._write_ddr_serial_diagnostic("总量包含未归类带宽", output)
            print(
                f"[DDR] {self.device_profile}单次采样 - "
                f"总:{sample_data.get('total', 0):.2f} MB/s{module_text}"
            )
            return True
        except subprocess.TimeoutExpired:
            self._set_ddr_error("DDR单次采样超时")
        except Exception as e:
            self._set_ddr_error(str(e))
        return False

    def _start_polled_ddr_sample(self):
        """Schedule one DDR sample without blocking the main metrics loop."""
        if not self.monitoring or self._stop_event.is_set():
            return
        if self.ddr_sample_thread and self.ddr_sample_thread.is_alive():
            return
        if time.monotonic() < self._ddr_next_retry_at:
            return

        def worker():
            success = False
            try:
                success = self._sample_polled_ddr()
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._set_ddr_error(str(exc))
                    print(f"[DDR] 单次采样异常: {self._short_serial_error(exc)}")
            finally:
                if success:
                    self._ddr_failure_count = 0
                    self._ddr_next_retry_at = 0.0
                elif not self._stop_event.is_set():
                    self._ddr_failure_count = min(self._ddr_failure_count + 1, 4)
                    retry_delay = min(30.0, max(2.0, 2 ** self._ddr_failure_count))
                    self._ddr_next_retry_at = time.monotonic() + retry_delay
                    print(f"[DDR] 本次采样失败，{retry_delay:.0f}秒后重试；主监控继续运行")

        self.ddr_sample_thread = threading.Thread(
            target=worker,
            name="ddr-sample",
            daemon=True,
        )
        self.ddr_sample_thread.start()

    def _start_ddr_monitoring(self):
        """启动DDR阻塞监控命令"""
        try:
            # 确保工具可用后再启动
            if not self._check_tool_exists():
                self._set_ddr_error("设备上未找到可执行DDR工具")
                print("[DDR] 工具不存在，无法启动DDR监控")
                return False

            self._execute_command(self._build_ddr_stop_command())
            command = self._build_ddr_command()
            print(f"[DDR] 启动阻塞监控命令: {command}")

            if self.connection_mode == "adb":
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                self.ddr_process = subprocess.Popen(
                    self._build_adb_ddr_args(command),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    bufsize=1,
                    creationflags=creationflags,
                )
            else:
                # 使用exec_command启动阻塞命令
                # 注意：这里直接使用 ssh_client.exec_command 可能会因为缓冲问题导致读取不及时
                # 使用 get_transport().open_session() 更底层一些，便于控制
                self.ddr_process = self.ssh_client.get_transport().open_session()
                self.ddr_process.get_pty(width=180, height=40)
                self.ddr_process.exec_command(command)
            self.ddr_status = "已启动，等待数据"

            # 启动读取线程
            self.ddr_reader_thread = threading.Thread(target=self._read_ddr_output)
            self.ddr_reader_thread.daemon = True
            self.ddr_reader_thread.start()

            print("[DDR] DDR监控进程已启动")
            return True

        except Exception as e:
            self._set_ddr_error(str(e))
            print(f"[DDR] 启动监控失败: {e}")
            return False

    def _read_ddr_output(self):
        """持续读取DDR监控输出"""
        buffer = ""

        def handle_text(text):
            nonlocal buffer
            if not text:
                return
            buffer += text
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    self._record_ddr_line(line.strip())

        try:
            if self.connection_mode == "adb":
                while self.monitoring and self.ddr_process:
                    line = self.ddr_process.stdout.readline() if self.ddr_process.stdout else ""
                    if line:
                        self._record_ddr_line(line.strip())
                        continue
                    if self.ddr_process.poll() is not None:
                        tail = "; ".join(self.ddr_output_tail[-5:])
                        if self.monitoring:
                            rc = self.ddr_process.returncode
                            if rc == 0:
                                self.ddr_status = "已退出"
                            else:
                                self._set_ddr_error(f"进程退出码 {rc}: {tail}")
                            print(f"[DDR] ADB监控进程退出: code={rc}, tail={tail}")
                        break
                    time.sleep(0.05)
                return

            while self.monitoring and self.ddr_process:
                has_data = False
                if self.ddr_process.recv_ready():
                    data = self.ddr_process.recv(4096).decode('utf-8', errors='ignore')
                    handle_text(data)
                    has_data = True

                if self.ddr_process.recv_stderr_ready():
                    data = self.ddr_process.recv_stderr(4096).decode('utf-8', errors='ignore')
                    handle_text(data)
                    has_data = True

                if self.ddr_process.exit_status_ready():
                    while self.ddr_process.recv_ready():
                        handle_text(self.ddr_process.recv(4096).decode('utf-8', errors='ignore'))
                    while self.ddr_process.recv_stderr_ready():
                        handle_text(self.ddr_process.recv_stderr(4096).decode('utf-8', errors='ignore'))
                    if buffer.strip():
                        self._record_ddr_line(buffer.strip())
                        buffer = ""

                    exit_code = self.ddr_process.recv_exit_status()
                    tail = "; ".join(self.ddr_output_tail[-5:])
                    if self.monitoring:
                        if exit_code == 0:
                            self.ddr_status = "已退出"
                        else:
                            self._set_ddr_error(f"进程退出码 {exit_code}: {tail}")
                        print(f"[DDR] 监控进程退出: code={exit_code}, tail={tail}")
                    break

                if not has_data:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高

        except Exception as e:
            self._set_ddr_error(str(e))
            print(f"[DDR读取] 异常: {e}")

    def _record_ddr_line(self, line):
        self.ddr_output_tail.append(line)
        self.ddr_output_tail = self.ddr_output_tail[-20:]
        if self.ddr_source != "vssdk" or re.match(r"\s*total\s+avg\s+bw", line, re.IGNORECASE):
            print(f"[DDR输出] {line}")
        self._parse_ddr_line(line)

    def _parse_ddr_line(self, line):
        ddr = self._get_ddr_spec()
        parser = ddr.get("line_parser") if ddr else None
        if parser:
            parsed = parser(line)
            if parsed:
                self.latest_ddr_data.update(parsed)
                return
        """解析DDR输出行"""
        try:
            falcon2_data = self._parse_falcon2_ddr_line(line)
            if falcon2_data:
                ddr_data = self.latest_ddr_data.copy()
                ddr_data.update(falcon2_data)
                self.latest_ddr_data = ddr_data
                self.ddr_status = "运行中"
                self.ddr_last_error = ""
                return

            # 查找包含模块带宽的行
            # 格式: "master bw(MB/s)       158.05    82.30    75.75     0.00  2017.36   447.48 ..."
            if 'master bw(MB/s)' in line:
                self._parse_ddr_bandwidth_line(line)
                return

            lower_line = line.lower()
            if 'ddr load:' in lower_line or ('load:' in lower_line and 'recorded' not in lower_line):
                self._parse_ddr_total_line(line)
        except Exception as e:
            print(f"[DDR解析] 失败: {e}, 行: {line[:100]}")

    @staticmethod
    def _parse_falcon2_ddr_line(line):
        """解析 Falcon2 DDR 总/写/读带宽及总线占用率。"""
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
        return {
            metric: float(match.group(2)),
            f"{metric}_occupancy": float(match.group(3)),
        }

    def _parse_ddr_bandwidth_line(self, line):
        """解析带宽行，提取各模块数据"""
        try:
            # 提取所有数字（带宽值）
            values = re.findall(r'[\d.]+', line)

            if values:
                # 根据表头顺序: cpu, cci_m1, cci_m2, gmac, isp, vicap, npu, crypto, rga, vpss, gpu, hdcp, vop, ufshc, others, total
                modules = ['cpu', 'cci_m1', 'cci_m2', 'gmac', 'isp', 'vicap', 'npu',
                          'crypto', 'rga', 'vpss', 'gpu', 'hdcp', 'vop', 'ufshc', 'others', 'total']

                ddr_data = {}
                for i, module in enumerate(modules):
                    if i < len(values):
                        ddr_data[module] = float(values[i])

                if 'total' not in ddr_data:
                    ddr_data['total'] = float(values[-1])

                # 保存最新数据
                self.latest_ddr_data = ddr_data
                self.ddr_status = "运行中"
                self.ddr_last_error = ""

                print(f"[DDR] 解析成功 - Total: {ddr_data.get('total', 0):.2f} MB/s, "
                      f"NPU: {ddr_data.get('npu', 0):.2f}, ISP: {ddr_data.get('isp', 0):.2f}")

        except Exception as e:
            print(f"[DDR解析] 带宽行解析失败: {e}")

    def _parse_ddr_total_line(self, line):
        """解析DDR简要输出中的总带宽。"""
        try:
            match = re.search(r'(?:ddr\s+load|load):\s*([0-9]+(?:\.[0-9]+)?)\s*MB/s', line, re.IGNORECASE)
            if not match:
                return

            total = float(match.group(1))
            ddr_data = self.latest_ddr_data.copy()
            ddr_data['total'] = total
            self.latest_ddr_data = ddr_data
            self.ddr_status = "运行中"
            self.ddr_last_error = ""
            print(f"[DDR] 解析总带宽 - Total: {total:.2f} MB/s")
        except Exception as e:
            print(f"[DDR解析] 总带宽行解析失败: {e}")

    def _monitor_loop(self, interval):
        """监控循环"""
        print(f"[性能监控] 开始监控循环，采样间隔: {interval}秒")
        while self.monitoring:
            try:
                # 获取各项指标
                npu_load = self._get_npu_load()
                cpu_usage = self._get_cpu_usage()
                memory_usage, memory_used_mb, memory_total_mb = self._get_memory_usage()
                # Falcon2 同时统计 MMZ 媒体内存；旧设备为零值
                mmz_usage, mmz_used_mb, mmz_total_mb = self._get_mmz_usage()
                mal_usage, mal_used_mb, mal_total_mb = self._get_mal_usage()

                if self._uses_polled_ddr() and self.ddr_status not in ("工具不可用", "不支持"):
                    self._start_polled_ddr_sample()

                # 从DDR实时数据中获取
                ddr_total = self.latest_ddr_data.get('total', 0.0)
                ddr_modules = self.latest_ddr_data.copy()

                timestamp = datetime.now().strftime("%H:%M:%S")

                # 详细日志
                mem_log = (f"MEM(free): {memory_used_mb:.0f}/{memory_total_mb:.0f} MB "
                           f"({memory_usage:.1f}%)")
                if self.memory_source == "mmz":
                    mem_log += (f" | MEM(mmz): {mmz_used_mb:.0f}/{mmz_total_mb:.0f} MB "
                                f"({mmz_usage:.1f}%)")
                if self.extra_memory_source == "mal":
                    mal_text = f"MAL:{mal_used_mb:.0f} MB"
                    if mal_total_mb > 0:
                        mal_text += f" ({mal_usage:.1f}%)"
                    else:
                        mal_text += " (总量未知)"
                    mem_log += f" | {mal_text}"
                if self.latest_npu_data.get("core_count", 2) <= 1:
                    npu_log = f"NPU:{npu_load:.1f}%"
                else:
                    npu_log = (f"NPU(Core0:{self.latest_npu_data['core0']:.1f}%, "
                               f"Core1:{self.latest_npu_data['core1']:.1f}%, "
                               f"综合:{npu_load:.1f}%)")
                print(f"[性能监控] {timestamp} | "
                      f"{npu_log} | "
                      f"CPU: {cpu_usage:.1f}% | "
                      f"{mem_log} | "
                      f"DDR总: {ddr_total:.2f} MB/s")

                # 更新历史数据
                self.history_data['timestamps'].append(timestamp)
                self.history_data['npu_core0'].append(self.latest_npu_data['core0'])
                self.history_data['npu_core1'].append(self.latest_npu_data['core1'])
                self.history_data['npu_load'].append(npu_load)
                self.history_data['cpu_usage'].append(cpu_usage)
                self.history_data['memory_used_mb'].append(memory_used_mb)
                self.history_data['memory_total_mb'].append(memory_total_mb)
                self.history_data['memory_usage'].append(memory_usage)
                self.history_data['mmz_used_mb'].append(mmz_used_mb)
                self.history_data['mmz_total_mb'].append(mmz_total_mb)
                self.history_data['mmz_usage'].append(mmz_usage)
                self.history_data['mal_used_mb'].append(mal_used_mb)
                self.history_data['mal_total_mb'].append(mal_total_mb)
                self.history_data['mal_usage'].append(mal_usage)
                self.history_data['ddr_total'].append(ddr_total)
                self.history_data['ddr_modules'].append(ddr_modules)

                # 限制历史数据长度（最多保留100个点）
                max_len = 100
                for key in self.history_data:
                    if len(self.history_data[key]) > max_len:
                        self.history_data[key] = self.history_data[key][-max_len:]

                # 更新完整历史数据
                self.full_history_data['timestamps'].append(timestamp)
                self.full_history_data['npu_core0'].append(self.latest_npu_data['core0'])
                self.full_history_data['npu_core1'].append(self.latest_npu_data['core1'])
                self.full_history_data['npu_load'].append(npu_load)
                self.full_history_data['cpu_usage'].append(cpu_usage)
                self.full_history_data['memory_used_mb'].append(memory_used_mb)
                self.full_history_data['memory_total_mb'].append(memory_total_mb)
                self.full_history_data['memory_usage'].append(memory_usage)
                self.full_history_data['mmz_used_mb'].append(mmz_used_mb)
                self.full_history_data['mmz_total_mb'].append(mmz_total_mb)
                self.full_history_data['mmz_usage'].append(mmz_usage)
                self.full_history_data['mal_used_mb'].append(mal_used_mb)
                self.full_history_data['mal_total_mb'].append(mal_total_mb)
                self.full_history_data['mal_usage'].append(mal_usage)
                self.full_history_data['ddr_total'].append(ddr_total)
                self.full_history_data['ddr_modules'].append(ddr_modules)

                # 更新最新数据
                self.latest_data = {
                    'timestamp': timestamp,
                    'npu_core0': self.latest_npu_data['core0'],
                    'npu_core1': self.latest_npu_data['core1'],
                    'npu_load': npu_load,
                    'npu_core_count': self.latest_npu_data.get('core_count', 2),
                    'cpu_usage': cpu_usage,
                    'memory_used_mb': memory_used_mb,
                    'memory_total_mb': memory_total_mb,
                    'memory_usage': memory_usage,
                    'mmz_used_mb': mmz_used_mb,
                    'mmz_total_mb': mmz_total_mb,
                    'mmz_usage': mmz_usage,
                    'mal_used_mb': mal_used_mb,
                    'mal_total_mb': mal_total_mb,
                    'mal_usage': mal_usage,
                    'memory_source': self.memory_source,
                    'ddr_total': ddr_total,
                    'ddr_modules': ddr_modules,
                    'ddr_source': self.ddr_source,
                    'device_profile': self.device_profile,
                    'ddr_status': self.ddr_status,
                    'ddr_error': self.ddr_last_error
                }

            except Exception as e:
                print(f"[性能监控] 数据采集失败: {e}")
                import traceback
                traceback.print_exc()

            time.sleep(interval)

    def get_ddr_module_data(self):
        """获取DDR各模块最新数据"""
        return self.latest_ddr_data.copy()

    def _execute_command(self, command):
        """执行设备命令，ADB模式走adb shell，SSH模式走exec_command。"""
        if self.connection_mode == "adb":
            success, output = self._run_adb_shell_command(command, timeout=15)
            if success:
                return output
            print(f"ADB命令执行失败 [{command}]: {output}")
            return ""

        if not self.ssh_client:
            return ""

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status == 0:
                return stdout.read().decode('utf-8').strip()
            else:
                error = stderr.read().decode('utf-8').strip()
                print(f"命令执行失败 [{command}]: {error}")
                return ""
        except Exception as e:
            print(f"命令执行异常 [{command}]: {e}")
            return ""

    def _detect_device_profile(self):
        if self.device_profile:
            return self.device_profile
        detected = self._execute_command(DEVICE_DETECTION_COMMAND).strip().lower()
        self.device_profile = detected if detected in DEVICE_RESOURCE_PROFILES else "falcon"
        print(f"[性能监控] 设备资源配置: {self.device_profile}")
        return self.device_profile

    def _get_resource_spec(self, resource_name):
        profile_name = self._detect_device_profile()
        return DEVICE_RESOURCE_PROFILES[profile_name].get(resource_name)

    def _collect_resource(self, resource_name):
        spec = self._get_resource_spec(resource_name)
        if not spec:
            return None
        sample_count = int(spec.get("samples", 1))
        outputs = []
        for index in range(sample_count):
            outputs.append(self._execute_command(spec["command"]))
            if index + 1 < sample_count:
                time.sleep(float(spec.get("sample_delay", 0)))
        parser_input = outputs if sample_count > 1 else outputs[0]
        return spec["parser"](parser_input)

    def _check_tool_exists(self):
        """检查设备上是否存在DDR带宽测试工具"""
        tool_path = self._get_remote_tool_path()
        if not tool_path:
            return False
        command = f"test -x {tool_path} && echo 'exists' || echo 'not_exists'"
        output = self._execute_command(command)
        return output == 'exists'

    def _push_tool_to_device(self, progress_callback=None):
        """推送DDR带宽测试工具到设备

        Args:
            progress_callback: 进度回调函数，接收(百分比, 消息)参数
        """
        local_tool_path = self._resolve_local_tool_path()
        remote_path = self._get_remote_tool_path()
        if not remote_path:
            return False, "当前设备未配置 DDR 工具"
        if not local_tool_path:
            return False, "未找到可用的本地 DDR 工具文件"

        if not os.path.exists(local_tool_path):
            return False, f"本地工具文件不存在: {local_tool_path}"

        try:
            print(f"[DDR工具] 开始推送DDR带宽测试工具到设备...")
            if progress_callback:
                progress_callback(10, "正在建立连接...")

            # 获取文件大小
            file_size = os.path.getsize(local_tool_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"[DDR工具] 文件大小: {file_size_mb:.2f} MB")

            if progress_callback:
                progress_callback(20, f"正在上传工具 ({file_size_mb:.2f} MB)...")

            if self.connection_mode == "adb":
                remote_dir = remote_path.rpartition("/")[0] or "/userdata"
                success, msg = self._run_adb_shell_command(f"mkdir -p {remote_dir}", timeout=10)
                if not success:
                    return False, f"创建{remote_dir}失败: {msg}"

                result = subprocess.run(
                    ["adb", "-s", self.adb_device_id, "push", local_tool_path, remote_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=120,
                )
                if result.returncode != 0:
                    return False, (result.stderr or result.stdout or "adb push失败").strip()
                if progress_callback:
                    progress_callback(90, "设置文件权限...")
                success, msg = self._run_adb_shell_command(f"chmod 755 {remote_path} && sync", timeout=10)
                if not success:
                    return False, f"chmod失败: {msg}"
                if progress_callback:
                    progress_callback(100, "验证文件...")
                if self._check_tool_exists():
                    return True, f"工具已通过ADB推送到 {remote_path}"
                return False, "工具推送后验证失败"

            if not self.ssh_client:
                return False, "SSH未连接，无法推送DDR工具"

            remote_dir = remote_path.rpartition("/")[0] or "/userdata"
            self._execute_command(f"mkdir -p {remote_dir}")
            sftp = self.ssh_client.open_sftp()

            # 确保目标目录存在
            if progress_callback:
                progress_callback(30, "检查目标目录...")

            try:
                sftp.stat(remote_dir)
            except FileNotFoundError:
                print(f"[DDR工具] 错误: {remote_dir} 目录不存在")
                sftp.close()
                return False, f"{remote_dir} 目录不存在"

            # 上传文件（带进度）
            def upload_progress(transferred, total):
                if progress_callback:
                    percent = 30 + int((transferred / total) * 60)  # 30-90%
                    msg = f"正在上传... {transferred/(1024*1024):.1f}/{total/(1024*1024):.1f} MB"
                    progress_callback(percent, msg)

            sftp.put(local_tool_path, remote_path, callback=upload_progress)

            if progress_callback:
                progress_callback(95, "设置文件权限...")

            # 设置可执行权限
            sftp.chmod(remote_path, 0o755)

            sftp.close()

            if progress_callback:
                progress_callback(100, "验证文件...")

            # 验证文件是否成功推送
            if self._check_tool_exists():
                print(f"[DDR工具] DDR带宽测试工具已成功推送到 {remote_path}")
                return True, f"工具已推送到 {remote_path}"
            else:
                return False, "工具推送后验证失败"

        except Exception as e:
            print(f"[DDR工具] 推送失败: {str(e)}")
            return False, f"工具推送失败: {str(e)}"

    def _ensure_tool_available(self, progress_callback=None):
        """确保DDR带宽测试工具可用"""
        if self.ddr_source is None:
            self._detect_ddr_source()

        if self.ddr_source == "unsupported":
            self.ddr_status = "不支持"
            return False

        ddr = self._get_ddr_spec()
        if ddr and ddr.get("transport") == "serial":
            # 串口探测不能阻塞性能监控启动；首次同步和后续重试由独立采样线程完成。
            self.ddr_status = "等待串口采样"
            return True

        if self._check_tool_exists():
            return True

        local_tool_path = self._resolve_local_tool_path()
        if not local_tool_path:
            print("本地 DDR 工具不存在，无法推送")
            return False

        print("设备上未找到DDR带宽测试工具，尝试推送...")
        success, msg = self._push_tool_to_device(progress_callback)
        if not success:
            print(f"工具推送失败: {msg}")
            return False
        return True

    def _detect_ddr_source(self):
        """Select the DDR collector configured for the detected platform."""
        ddr = DEVICE_RESOURCE_PROFILES[self._detect_device_profile()].get("ddr")
        self.ddr_source = ddr.get("source") if ddr else "unsupported"
        print(f"[DDR] source: {self.ddr_source}")

    def _detect_npu_source(self):
        """Select the NPU collector configured for the detected platform."""
        self.npu_source = self._detect_device_profile()
        print(f"[NPU] source: {self.npu_source}")

    @staticmethod
    def _parse_npu_load(output):
        """解析 Falcon2 VSSDK 或旧设备 RKNPU 的负载输出。"""
        if not output:
            return None

        core0_match = re.search(r"Core0:\s*([\d.]+)%", output, re.IGNORECASE)
        core1_match = re.search(r"Core1:\s*([\d.]+)%", output, re.IGNORECASE)
        if core0_match and core1_match:
            core0 = float(core0_match.group(1))
            core1 = float(core1_match.group(1))
            return {"core0": core0, "core1": core1, "avg": (core0 + core1) / 2.0}

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
                lowered_parts = [part.lower() for part in parts]
                if "clusterid" in lowered_parts and "hw_utilization" in lowered_parts:
                    utilization_index = lowered_parts.index("hw_utilization")
                continue

            if not parts or not parts[0].isdigit() or len(parts) <= utilization_index:
                continue
            utilization = parts[utilization_index].rstrip("%")
            cluster_loads[int(parts[0])] = float(utilization)

        if cluster_loads:
            core0 = cluster_loads.get(0, 0.0)
            core1 = cluster_loads.get(1, 0.0)
            weighted_load = (core0 * 4.0 + core1 * 2.0) / 6.0
            return {"core0": core0, "core1": core1, "avg": weighted_load}
        return None

    def _get_npu_load(self):
        """获取 NPU 占用率（分别统计 Core0 和 Core1）。"""
        if self.npu_source is None:
            self._detect_npu_source()

        npu_resource = DEVICE_RESOURCE_PROFILES[self.npu_source]["npu"]
        output = self._execute_command(npu_resource["command"])
        if self.npu_source == "vssdk":
            print(f"[NPU] 已读取 VSSDK 统计信息，共 {len(output)} 字符")
        else:
            # Ambarella 输出包含整段任务表，避免每个采样周期把完整回显刷入控制台。
            if self.npu_source == "ambarella":
                print(f"[NPU] 已读取 Ambarella 统计信息，共 {len(output)} 字符")
            else:
                print(f"[NPU] 命令输出: {output[:500]}")

        try:
            result = npu_resource["parser"](output)
            if result is not None:
                alpha = npu_resource.get("smoothing_alpha")
                if alpha and self._npu_smoothed_load is not None:
                    result = dict(result)
                    result["avg"] = alpha * result["avg"] + (1.0 - alpha) * self._npu_smoothed_load
                    result["core0"] = alpha * result["core0"] + (1.0 - alpha) * self.latest_npu_data.get("core0", 0.0)
                if alpha:
                    self._npu_smoothed_load = result["avg"]
                self.latest_npu_data = result
                if result.get("core_count", 2) <= 1:
                    core_text = f"NPU: {result['avg']:.1f}%"
                else:
                    core_text = f"Core0: {result['core0']:.1f}%"
                    core_text += f", Core1: {result['core1']:.1f}%"
                    core_text += f", 综合: {result['avg']:.1f}%"
                print(f"[NPU] {core_text}")
                return result["avg"]
            alpha = npu_resource.get("smoothing_alpha")
            if alpha and self._npu_smoothed_load is not None:
                decayed = (1.0 - alpha) * self._npu_smoothed_load
                self._npu_smoothed_load = decayed
                self.latest_npu_data = {
                    "core0": decayed,
                    "core1": 0.0,
                    "avg": decayed,
                    "core_count": npu_resource.get("core_count", 1),
                }
                return decayed
        except (TypeError, ValueError) as e:
            print(f"[NPU] 解析失败: {e}, 回显长度: {len(output)}")

        core_count = npu_resource.get("core_count", 2)
        self.latest_npu_data = {"core0": 0.0, "core1": 0.0, "avg": 0.0, "core_count": core_count}
        return 0.0

    def _get_cpu_usage(self):
        """Get CPU utilization using the platform resource registry."""
        try:
            cpu_usage = self._collect_resource("cpu")
            if cpu_usage is not None:
                return cpu_usage
        except (TypeError, ValueError) as e:
            print(f"[CPU] registered parser failed: {e}")
        # 使用更可靠的命令 - 直接从 /proc/stat 计算
        output1 = self._execute_command("cat /proc/stat | grep '^cpu '")
        time.sleep(0.5)
        output2 = self._execute_command("cat /proc/stat | grep '^cpu '")

        print(f"[CPU] 第一次采样: {output1}")
        print(f"[CPU] 第二次采样: {output2}")

        if output1 and output2:
            try:
                # 解析 /proc/stat 格式: cpu  user nice system idle iowait irq softirq steal
                vals1 = list(map(int, output1.split()[1:]))
                vals2 = list(map(int, output2.split()[1:]))

                # 计算差值
                diffs = [vals2[i] - vals1[i] for i in range(len(vals1))]
                total = sum(diffs)
                idle = diffs[3]  # idle是第4个值（索引3）

                if total > 0:
                    cpu_usage = (1 - idle / total) * 100.0
                    print(f"[CPU] 计算结果: {cpu_usage:.1f}%")
                    return cpu_usage
            except Exception as e:
                print(f"[CPU] 解析失败: {e}")

        # 备用方案：使用top命令
        output = self._execute_command("top -bn1 | head -5")
        print(f"[CPU备用] 命令输出: {output[:200]}")
        if output:
            try:
                import re
                # 查找类似 "32.5 idle" 的模式
                match = re.search(r'(\d+\.?\d*)\s*id(?:le)?', output, re.IGNORECASE)
                if match:
                    idle = float(match.group(1))
                    return 100.0 - idle
            except Exception as e:
                print(f"[CPU备用] 解析失败: {e}")
        return 0.0

    def _detect_memory_source(self):
        """Detect whether the platform provides an additional memory pool."""
        profile = DEVICE_RESOURCE_PROFILES[self._detect_device_profile()]
        extra_memory = profile.get("extra_memory") or {}
        self.extra_memory_source = extra_memory.get("source")
        self.memory_source = "mmz" if self.extra_memory_source == "mmz" else "free"
        print(f"[MEM] source: free, extra: {self.extra_memory_source or 'none'}")

    @staticmethod
    def _parse_memory_usage(output):
        """解析内存统计输出，兼容 Falcon2 MMZ 与旧设备 free 两种格式。

        传入 MMZ 输出时返回 MMZ 统计，传入 free 输出时返回 Linux 系统内存统计。
        """
        if not output:
            return None

        mmz_match = re.search(
            r"mmz\s+use\s+summary:\s*total=(\d+(?:\.\d+)?)KB\s+"
            r"used=(\d+(?:\.\d+)?)KB\s+free=(\d+(?:\.\d+)?)KB",
            output,
            re.IGNORECASE,
        )
        if mmz_match:
            total_mb = float(mmz_match.group(1)) / 1024.0
            used_mb = float(mmz_match.group(2)) / 1024.0
            usage_percent = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0
            return usage_percent, used_mb, total_mb

        for line in output.splitlines():
            parts = line.split()
            if parts and parts[0].rstrip(":").lower() == "mem" and len(parts) >= 3:
                total_mb = float(parts[1])
                used_mb = float(parts[2])
                usage_percent = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0
                return usage_percent, used_mb, total_mb

        return None

    def _get_memory_usage(self):
        """Get Linux system memory utilization for every platform."""
        try:
            result = self._collect_resource("memory")
            if result is not None:
                return result
        except (TypeError, ValueError) as e:
            print(f"[MEM] registered parser failed: {e}")
        if self.memory_source is None:
            self._detect_memory_source()

        output = self._execute_command("free -m")
        print(f"[内存-free] 命令输出: {output}")

        try:
            result = self._parse_memory_usage(output)
            if result is not None:
                usage_percent, used_mb, total_mb = result
                print(f"[内存-free] 计算结果: {used_mb:.2f}/{total_mb:.2f} MB = {usage_percent:.1f}%")
                return result
        except (TypeError, ValueError) as e:
            print(f"[内存-free] 解析失败: {e}, 原始输出: {output}")

        return 0.0, 0.0, 0.0

    def _get_mmz_usage(self):
        """获取 Falcon2 MMZ 媒体内存占用率；非 Falcon2 设备返回零值。

        Falcon2 同时统计 MMZ 与 free，两者独立采集互不影响。
        """
        if self.memory_source is None:
            self._detect_memory_source()

        if self.memory_source != "mmz":
            return 0.0, 0.0, 0.0

        extra_memory = self._get_resource_spec("extra_memory")
        if not extra_memory:
            return 0.0, 0.0, 0.0

        output = self._execute_command(extra_memory["command"])
        print(f"[内存-mmz] 已读取统计信息，共 {len(output)} 字符")

        try:
            result = extra_memory["parser"](output)
            if result is not None:
                usage_percent, used_mb, total_mb = result
                print(f"[内存-mmz] 计算结果: {used_mb:.2f}/{total_mb:.2f} MB = {usage_percent:.1f}%")
                return result
            # MMZ 接口偶发不可读时返回零值，不影响系统内存统计
            print("[内存-mmz] 未匹配到 mmz 统计行")
        except (TypeError, ValueError) as e:
            print(f"[内存-mmz] 解析失败: {e}, 回显长度: {len(output)}")

        return 0.0, 0.0, 0.0

    def _get_mal_usage(self):
        """Read Ambarella MAL allocation ranges independently from Linux free."""
        if self.memory_source is None:
            self._detect_memory_source()
        if self.extra_memory_source != "mal":
            return 0.0, 0.0, 0.0

        extra_memory = self._get_resource_spec("extra_memory")
        if not extra_memory:
            return 0.0, 0.0, 0.0
        output = self._execute_command(extra_memory["command"])
        print(f"[内存-mal] 已读取统计信息，共 {len(output)} 字符")
        try:
            result = extra_memory["parser"](output)
            if result is not None:
                usage_percent, used_mb, total_mb = result
                if total_mb > 0:
                    print(f"[内存-mal] 计算结果: {used_mb:.2f}/{total_mb:.2f} MB = {usage_percent:.1f}%")
                else:
                    print(f"[内存-mal] 已分配: {used_mb:.2f} MB（回显未提供总容量）")
                return result
            print("[内存-mal] 未匹配到 MAL 区间")
        except (TypeError, ValueError) as e:
            print(f"[内存-mal] 解析失败: {e}, 回显长度: {len(output)}")
        return 0.0, 0.0, 0.0


    def get_latest_data(self):
        """获取最新的监控数据"""
        return self.latest_data.copy()

    def get_history_data(self, use_full_history=False):
        """获取历史数据

        Args:
            use_full_history: 是否使用完整历史数据（不限制100个点）
                             默认为False保持向后兼容
        """
        if use_full_history:
            return self.full_history_data.copy()
        return self.history_data.copy()

    def export_data(self, filename="performance_data.csv"):
        """导出历史数据到CSV"""
        import csv

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['时间戳', 'NPU占用(%)', 'CPU占用(%)',
                                 '内存占用(%)', 'MMZ占用(%)', 'MAL已分配(MB)',
                                 'MAL占用(%)', 'DDR带宽(MB/s)'])

                for i in range(len(self.full_history_data['timestamps'])):
                    writer.writerow([
                        self.full_history_data['timestamps'][i],
                        self.full_history_data['npu_load'][i],
                        self.full_history_data['cpu_usage'][i],
                        self.full_history_data['memory_usage'][i],
                        self.full_history_data['mmz_usage'][i],
                        self.full_history_data['mal_used_mb'][i],
                        self.full_history_data['mal_usage'][i],
                        self.full_history_data['ddr_total'][i]
                    ])

            return True, f"数据已导出到 {filename}"
        except Exception as e:
            return False, f"导出失败: {str(e)}"
