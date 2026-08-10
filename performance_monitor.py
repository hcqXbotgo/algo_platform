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


class PerformanceMonitor:
    """性能监控器"""

    FALCON2_DDR_FREQ = 3733

    def __init__(self):
        self.monitoring = False
        self.ssh_client = None
        self.adb_device_id = None
        self.connection_mode = None
        self.device_ip = None
        self.ddr_freq = 1848
        self.memory_source = None
        self.npu_source = None
        self.ddr_source = None
        self.history_data = {
            'timestamps': [],
            'npu_core0': [],  # NPU Core0占用率
            'npu_core1': [],  # NPU Core1占用率
            'npu_load': [],   # NPU综合占用率
            'cpu_usage': [],
            'memory_used_mb': [],  # 内存实际使用量(MB)
            'memory_total_mb': [], # 内存总量(MB)
            'memory_usage': [],    # 内存占用率(%)
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
            'ddr_total': [],
            'ddr_modules': []
        }
        self.latest_data = {}
        self.monitor_thread = None
        self.tool_path = "/userdata/rk-msch-probe-for-user-64bit-1"
        self.falcon2_ddr_tool_path = "/userdata/ddr_bandwidth.sh"
        self.local_tool_path = None  # 本地工具文件路径，需要外部设置
        bundled_tool = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "rk-msch-probe-for-user-64bit-1",
        )
        if os.path.exists(bundled_tool):
            self.local_tool_path = bundled_tool

        # DDR监控相关
        self.ddr_process = None  # 阻塞命令的SSH通道
        self.ddr_reader_thread = None  # 读取输出的线程
        self.latest_ddr_data = {}  # 最新解析的DDR数据
        self.ddr_status = "未启动"
        self.ddr_last_error = ""
        self.ddr_output_tail = []

        # NPU监控相关
        self.latest_npu_data = {'core0': 0.0, 'core1': 0.0, 'avg': 0.0}

    def set_tool_path(self, local_path):
        """设置本地工具文件路径"""
        if os.path.exists(local_path):
            self.local_tool_path = local_path
            return True, f"工具路径已设置: {local_path}"
        else:
            return False, f"工具文件不存在: {local_path}"

    def _get_fallback_tool_path(self):
        """获取随上位机一起打包的 DDR 工具路径。"""
        bundled_tool = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "rk-msch-probe-for-user-64bit-1",
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
            self.local_tool_path = fallback_tool
            return fallback_tool

        return None

    def _get_usb_adb_device_id(self):
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
        self.latest_ddr_data = {}
        self.ddr_status = "初始化中"
        self.ddr_last_error = ""
        self.ddr_output_tail = []
        self.memory_source = None
        self.npu_source = None
        self.ddr_source = None

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

                self.ssh_client, ssh_success, ssh_msg = connect_ssh_with_retry(device_ip)
                if not ssh_success:
                    print(f"[性能监控] SSH直连失败，尝试通过ADB启动SSH服务: {ssh_msg}")
                    adb_success, adb_start_msg = DeviceManager().ensure_ssh_service_via_adb()
                    if adb_success:
                        self.ssh_client, ssh_success, ssh_msg = connect_ssh_with_retry(device_ip, retries=3)
                    if not ssh_success:
                        raise Exception(f"{ssh_msg}; ADB启动SSH服务: {adb_start_msg}")

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
            'ddr_total': [],
            'ddr_modules': []
        }

        # 检查DDR工具并启动DDR监控。当前函数运行在后台 worker 中，可以同步等待结果。
        if progress_callback:
            progress_callback(50, "检查DDR测试工具...")

        def ddr_progress(percent, message):
            if progress_callback:
                progress_callback(50 + int(percent * 0.3), message)

        if self._ensure_tool_available(ddr_progress):
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
            if self.ddr_source == "vssdk":
                self.ddr_status = "已禁用"
                print("[性能监控] Falcon2 DDR监控已禁用，跳过ddr_bandwidth.sh")
                if progress_callback:
                    progress_callback(90, "Falcon2 DDR监控已禁用")
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

        self._execute_command(self._build_ddr_stop_command())
        self.ddr_status = "已停止"

        # 等待读取线程结束
        if self.ddr_reader_thread:
            self.ddr_reader_thread.join(timeout=3)
            self.ddr_reader_thread = None

        # 停止主监控线程
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

        # 关闭SSH连接
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None

    def _set_ddr_error(self, message):
        self.ddr_status = "异常"
        self.ddr_last_error = message

    def _build_ddr_command(self):
        if self.ddr_source == "vssdk":
            return (
                "cd /userdata && ./ddr_bandwidth.sh "
                f"-p 100 -f {self.FALCON2_DDR_FREQ} "
                "-w 32 -b 0x100000 -t 1 -d 0xf00000"
            )
        tool_dir = os.path.dirname(self.tool_path) or "/userdata"
        tool_name = os.path.basename(self.tool_path)
        return f"cd {tool_dir} && ./{tool_name} -c rk3576 -f {self.ddr_freq} -l 2 2>&1"

    def _build_ddr_stop_command(self):
        if self.ddr_source == "vssdk":
            return "pkill -f '[d]dr_bandwidth' >/dev/null 2>&1 || true"
        return "pkill -f '[r]k-msch-probe-for-user-64bit-1' >/dev/null 2>&1 || true"

    def _build_adb_ddr_args(self, command):
        args = ["adb", "-s", self.adb_device_id, "shell"]
        if self.ddr_source == "vssdk":
            args.append("-tt")
        args.append(command)
        return args

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

                # 从DDR实时数据中获取
                ddr_total = self.latest_ddr_data.get('total', 0.0)
                ddr_modules = self.latest_ddr_data.copy()

                timestamp = datetime.now().strftime("%H:%M:%S")

                # 详细日志
                print(f"[性能监控] {timestamp} | "
                      f"NPU(Core0:{self.latest_npu_data['core0']:.1f}%, "
                      f"Core1:{self.latest_npu_data['core1']:.1f}%, "
                      f"综合:{npu_load:.1f}%) | "
                      f"CPU: {cpu_usage:.1f}% | "
                      f"MEM: {memory_used_mb:.0f}/{memory_total_mb:.0f} MB ({memory_usage:.1f}%) | "
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
                self.full_history_data['ddr_total'].append(ddr_total)
                self.full_history_data['ddr_modules'].append(ddr_modules)

                # 更新最新数据
                self.latest_data = {
                    'timestamp': timestamp,
                    'npu_core0': self.latest_npu_data['core0'],
                    'npu_core1': self.latest_npu_data['core1'],
                    'npu_load': npu_load,
                    'cpu_usage': cpu_usage,
                    'memory_used_mb': memory_used_mb,
                    'memory_total_mb': memory_total_mb,
                    'memory_usage': memory_usage,
                    'ddr_total': ddr_total,
                    'ddr_modules': ddr_modules,
                    'ddr_source': self.ddr_source,
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

    def _check_tool_exists(self):
        """检查设备上是否存在DDR带宽测试工具"""
        tool_path = self.falcon2_ddr_tool_path if self.ddr_source == "vssdk" else self.tool_path
        command = f"test -x {tool_path} && echo 'exists' || echo 'not_exists'"
        output = self._execute_command(command)
        return output == 'exists'

    def _push_tool_to_device(self, progress_callback=None):
        """推送DDR带宽测试工具到设备

        Args:
            progress_callback: 进度回调函数，接收(百分比, 消息)参数
        """
        local_tool_path = self._resolve_local_tool_path()
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
                success, msg = self._run_adb_shell_command("mkdir -p /userdata", timeout=10)
                if not success:
                    return False, f"创建/userdata失败: {msg}"

                result = subprocess.run(
                    ["adb", "-s", self.adb_device_id, "push", local_tool_path, self.tool_path],
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
                success, msg = self._run_adb_shell_command(f"chmod 755 {self.tool_path} && sync", timeout=10)
                if not success:
                    return False, f"chmod失败: {msg}"
                if progress_callback:
                    progress_callback(100, "验证文件...")
                if self._check_tool_exists():
                    return True, f"工具已通过ADB推送到 {self.tool_path}"
                return False, "工具推送后验证失败"

            if not self.ssh_client:
                return False, "SSH未连接，无法推送DDR工具"

            self._execute_command("mkdir -p /userdata")
            sftp = self.ssh_client.open_sftp()

            # 确保目标目录存在
            if progress_callback:
                progress_callback(30, "检查目标目录...")

            try:
                sftp.stat('/userdata')
            except FileNotFoundError:
                print("[DDR工具] 错误: /userdata 目录不存在")
                sftp.close()
                return False, "/userdata 目录不存在"

            # 上传文件（带进度）
            remote_path = self.tool_path

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

        # Falcon2 暂不执行 ddr_bandwidth.sh，避免运行脚本后 ADB 断开。
        if self.ddr_source == "vssdk":
            return False

        if self._check_tool_exists():
            return True

        if self.ddr_source == "vssdk":
            print(f"Falcon2 DDR工具不存在或不可执行: {self.falcon2_ddr_tool_path}")
            return False

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
        """检测 DDR 统计接口；Falcon2 使用 ddr_bandwidth.sh。"""
        output = self._execute_command(
            "if [ -e /proc/vssdk/npu ] || [ -e /proc/vssdk/mmz ] || "
            "[ -e /userdata/ddr_bandwidth.sh ]; then echo vssdk; else echo rknpu; fi"
        )
        self.ddr_source = "vssdk" if output.strip() == "vssdk" else "rknpu"
        print(f"[DDR] 使用数据源: {self.ddr_source}")

    def _detect_npu_source(self):
        """检测设备 NPU 统计接口；Falcon2 使用 VSSDK，旧设备使用 RKNPU。"""
        output = self._execute_command(
            "if [ -r /proc/vssdk/npu ]; then echo vssdk; else echo rknpu; fi"
        )
        self.npu_source = "vssdk" if output.strip() == "vssdk" else "rknpu"
        print(f"[NPU] 使用数据源: {self.npu_source}")

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

        command = (
            "cat /proc/vssdk/npu"
            if self.npu_source == "vssdk"
            else "cat /sys/kernel/debug/rknpu/load"
        )
        output = self._execute_command(command)
        if self.npu_source == "vssdk":
            print(f"[NPU] 已读取 VSSDK 统计信息，共 {len(output)} 字符")
        else:
            print(f"[NPU] 命令输出: {output}")

        try:
            result = self._parse_npu_load(output)
            if result is None and self.npu_source == "vssdk":
                result = self._parse_npu_load(
                    self._execute_command("cat /sys/kernel/debug/rknpu/load")
                )
            if result is not None:
                self.latest_npu_data = result
                print(
                    f"[NPU] Core0: {result['core0']:.1f}%, "
                    f"Core1: {result['core1']:.1f}%, 综合: {result['avg']:.1f}%"
                )
                return result["avg"]
        except (TypeError, ValueError) as e:
            print(f"[NPU] 解析失败: {e}, 原始输出: {output}")

        self.latest_npu_data = {"core0": 0.0, "core1": 0.0, "avg": 0.0}
        return 0.0

    def _get_cpu_usage(self):
        """获取CPU占用率"""
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
        """检测设备内存统计接口；Falcon2 使用 MMZ，旧设备使用 free。"""
        output = self._execute_command(
            "if [ -r /proc/vssdk/mmz ]; then echo mmz; else echo free; fi"
        )
        self.memory_source = "mmz" if output.strip() == "mmz" else "free"
        print(f"[内存] 使用数据源: {self.memory_source}")

    @staticmethod
    def _parse_memory_usage(output):
        """解析 Falcon2 MMZ 或旧设备 free 输出。"""
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
        """获取内存占用率和实际使用量。"""
        if self.memory_source is None:
            self._detect_memory_source()

        command = "cat /proc/vssdk/mmz" if self.memory_source == "mmz" else "free -m"
        output = self._execute_command(command)
        print(f"[内存] 命令输出: {output}")

        try:
            result = self._parse_memory_usage(output)
            if result is None and self.memory_source == "mmz":
                # MMZ 接口偶发不可读时，尽量保留 Linux 内存统计数据。
                result = self._parse_memory_usage(self._execute_command("free -m"))
            if result is not None:
                usage_percent, used_mb, total_mb = result
                print(f"[内存] 计算结果: {used_mb:.2f}/{total_mb:.2f} MB = {usage_percent:.1f}%")
                return result
        except (TypeError, ValueError) as e:
            print(f"[内存] 解析失败: {e}, 原始输出: {output}")

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
                writer.writerow(['时间戳', 'NPU占用(%)', 'CPU占用(%)', '内存占用(%)', 'DDR带宽(MB/s)'])

                for i in range(len(self.full_history_data['timestamps'])):
                    writer.writerow([
                        self.full_history_data['timestamps'][i],
                        self.full_history_data['npu_load'][i],
                        self.full_history_data['cpu_usage'][i],
                        self.full_history_data['memory_usage'][i],
                        self.full_history_data['ddr_total'][i]
                    ])

            return True, f"数据已导出到 {filename}"
        except Exception as e:
            return False, f"导出失败: {str(e)}"
