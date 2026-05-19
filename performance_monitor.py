# -*- coding: utf-8 -*-
"""
性能监控模块
功能：监控NPU、CPU、内存占用和DDR带宽
注意：DDR带宽通过实时阻塞命令读取，已移除旧的轮询获取方式
"""

import paramiko
import threading
import time
import os
from datetime import datetime


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.monitoring = False
        self.ssh_client = None
        self.device_ip = None
        self.ddr_freq = 1848
        self.history_data = {
            'timestamps': [],
            'npu_core0': [],  # NPU Core0占用率
            'npu_core1': [],  # NPU Core1占用率
            'npu_load': [],   # NPU平均占用率
            'cpu_usage': [],
            'memory_used_mb': [],  # 内存实际使用量(MB)
            'memory_total_mb': [], # 内存总量(MB)
            'memory_usage': [],    # 内存占用率(%)
            'ddr_total': [],       # DDR总带宽
            'ddr_modules': []      # 各模块带宽: {'cpu': x, 'isp': y, 'npu': z, ...}
        }
        self.latest_data = {}
        self.monitor_thread = None
        self.tool_path = "/userdata/rk-msch-probe-for-user-64bit-1"
        self.local_tool_path = None  # 本地工具文件路径，需要外部设置
        
        # DDR监控相关
        self.ddr_process = None  # 阻塞命令的SSH通道
        self.ddr_reader_thread = None  # 读取输出的线程
        self.latest_ddr_data = {}  # 最新解析的DDR数据
        
        # NPU监控相关
        self.latest_npu_data = {'core0': 0.0, 'core1': 0.0, 'avg': 0.0}
        
    def set_tool_path(self, local_path):
        """设置本地工具文件路径"""
        if os.path.exists(local_path):
            self.local_tool_path = local_path
            return True, f"工具路径已设置: {local_path}"
        else:
            return False, f"工具文件不存在: {local_path}"
        
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
        
        # 建立SSH连接
        try:
            if progress_callback:
                progress_callback(20, "正在建立SSH连接...")
            print(f"[性能监控] 正在连接设备 {device_ip}...")
            
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(device_ip, port=22, username='root', password='', timeout=10)
            
            if progress_callback:
                progress_callback(40, "SSH连接成功")
            print(f"[性能监控] SSH连接成功")
            
        except Exception as e:
            self.monitoring = False
            raise Exception(f"SSH连接失败: {str(e)}")
            
        # 清空历史数据
        self.history_data = {
            'timestamps': [],
            'npu_core0': [],  # NPU Core0占用率
            'npu_core1': [],  # NPU Core1占用率
            'npu_load': [],   # NPU平均占用率
            'cpu_usage': [],
            'memory_used_mb': [],  # 内存实际使用量(MB)
            'memory_total_mb': [], # 内存总量(MB)
            'memory_usage': [],    # 内存占用率(%)
            'ddr_total': [],       # DDR总带宽
            'ddr_modules': []      # 各模块带宽: {'cpu': x, 'isp': y, 'npu': z, ...}
        }
        
        # 检查DDR工具并启动DDR监控（在后台线程中执行，避免阻塞主流程）
        if progress_callback:
            progress_callback(50, "检查DDR测试工具...")
        
        def init_ddr_in_thread():
            # 1. 确保工具可用
            if self._ensure_tool_available(progress_callback):
                # 2. 启动DDR监控进程
                if progress_callback:
                    progress_callback(85, "启动DDR监控...")
                self._start_ddr_monitoring()
            else:
                print("[性能监控] 警告: DDR工具不可用，将跳过DDR监控")
                if progress_callback:
                    progress_callback(85, "DDR工具不可用，跳过DDR监控")
        
        # 在后台线程中初始化DDR监控
        ddr_init_thread = threading.Thread(target=init_ddr_in_thread)
        ddr_init_thread.daemon = True
        ddr_init_thread.start()
        
        # 启动监控线程
        if progress_callback:
            progress_callback(90, "启动主监控线程...")
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,))
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        if progress_callback:
            progress_callback(100, "监控已启动！")
        
        print(f"[性能监控] 监控线程已启动")
        
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        
        # 停止DDR监控进程
        if self.ddr_process:
            try:
                self.ddr_process.close()
                print("[DDR] 已停止DDR监控进程")
            except:
                pass
            self.ddr_process = None
        
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
            
    def _start_ddr_monitoring(self):
        """启动DDR阻塞监控命令"""
        try:
            # 确保工具可用后再启动
            if not self._check_tool_exists():
                print("[DDR] 工具不存在，无法启动DDR监控")
                return

            command = f"{self.tool_path} -c rk3576 -f {self.ddr_freq}"
            print(f"[DDR] 启动阻塞监控命令: {command}")
            
            # 使用exec_command启动阻塞命令
            # 注意：这里直接使用 ssh_client.exec_command 可能会因为缓冲问题导致读取不及时
            # 使用 get_transport().open_session() 更底层一些，便于控制
            self.ddr_process = self.ssh_client.get_transport().open_session()
            self.ddr_process.exec_command(command)
            
            # 启动读取线程
            self.ddr_reader_thread = threading.Thread(target=self._read_ddr_output)
            self.ddr_reader_thread.daemon = True
            self.ddr_reader_thread.start()
            
            print("[DDR] DDR监控进程已启动")
            
        except Exception as e:
            print(f"[DDR] 启动监控失败: {e}")
            
    def _read_ddr_output(self):
        """持续读取DDR监控输出"""
        buffer = ""
        
        try:
            while self.monitoring and self.ddr_process:
                # 读取输出
                if self.ddr_process.recv_ready():
                    data = self.ddr_process.recv(4096).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    # 按行处理
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            self._parse_ddr_line(line)
                else:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    
        except Exception as e:
            print(f"[DDR读取] 异常: {e}")
            
    def _parse_ddr_line(self, line):
        """解析DDR输出行"""
        try:
            # 查找包含模块带宽的行
            # 格式: "master bw(MB/s)       158.05    82.30    75.75     0.00  2017.36   447.48 ..."
            if 'master bw(MB/s)' in line:
                self._parse_ddr_bandwidth_line(line)
        except Exception as e:
            print(f"[DDR解析] 失败: {e}, 行: {line[:100]}")
            
    def _parse_ddr_bandwidth_line(self, line):
        """解析带宽行，提取各模块数据"""
        try:
            import re
            
            # 提取所有数字（带宽值）
            values = re.findall(r'[\d.]+', line)
            
            if len(values) >= 14:  # 确保有足够的模块数据
                # 根据表头顺序: cpu, cci_m1, cci_m2, gmac, isp, vicap, npu, crypto, rga, vpss, gpu, hdcp, vop, ufshc, others, total
                modules = ['cpu', 'cci_m1', 'cci_m2', 'gmac', 'isp', 'vicap', 'npu', 
                          'crypto', 'rga', 'vpss', 'gpu', 'hdcp', 'vop', 'ufshc', 'others', 'total']
                
                ddr_data = {}
                for i, module in enumerate(modules):
                    if i < len(values):
                        ddr_data[module] = float(values[i])
                
                # 保存最新数据
                self.latest_ddr_data = ddr_data
                
                print(f"[DDR] 解析成功 - Total: {ddr_data.get('total', 0):.2f} MB/s, "
                      f"NPU: {ddr_data.get('npu', 0):.2f}, ISP: {ddr_data.get('isp', 0):.2f}")
                
        except Exception as e:
            print(f"[DDR解析] 带宽行解析失败: {e}")

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
                      f"平均:{npu_load:.1f}%) | "
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
                    'ddr_modules': ddr_modules
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
        """执行SSH命令"""
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
        command = f"test -f {self.tool_path} && echo 'exists' || echo 'not_exists'"
        output = self._execute_command(command)
        return output == 'exists'
        
    def _push_tool_to_device(self, progress_callback=None):
        """推送DDR带宽测试工具到设备
        
        Args:
            progress_callback: 进度回调函数，接收(百分比, 消息)参数
        """
        if not self.local_tool_path:
            return False, "未设置本地工具文件路径"
            
        if not os.path.exists(self.local_tool_path):
            return False, f"本地工具文件不存在: {self.local_tool_path}"
        
        try:
            print(f"[DDR工具] 开始推送DDR带宽测试工具到设备...")
            if progress_callback:
                progress_callback(10, "正在建立连接...")
            
            # 获取文件大小
            file_size = os.path.getsize(self.local_tool_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"[DDR工具] 文件大小: {file_size_mb:.2f} MB")
            
            if progress_callback:
                progress_callback(20, f"正在上传工具 ({file_size_mb:.2f} MB)...")
            
            # 创建SFTP连接
            transport = paramiko.Transport((self.device_ip, 22))
            transport.connect(username='root', password='')
            
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # 确保目标目录存在
            if progress_callback:
                progress_callback(30, "检查目标目录...")
            
            try:
                sftp.stat('/userdata')
            except FileNotFoundError:
                print("[DDR工具] 错误: /userdata 目录不存在")
                return False, "/userdata 目录不存在"
            
            # 上传文件（带进度）
            remote_path = self.tool_path
            
            def upload_progress(transferred, total):
                if progress_callback:
                    percent = 30 + int((transferred / total) * 60)  # 30-90%
                    msg = f"正在上传... {transferred/(1024*1024):.1f}/{total/(1024*1024):.1f} MB"
                    progress_callback(percent, msg)
            
            sftp.put(self.local_tool_path, remote_path, callback=upload_progress)
            
            if progress_callback:
                progress_callback(95, "设置文件权限...")
            
            # 设置可执行权限
            sftp.chmod(remote_path, 0o755)
            
            sftp.close()
            transport.close()
            
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
        if not self._check_tool_exists():
            print("设备上未找到DDR带宽测试工具，尝试推送...")
            success, msg = self._push_tool_to_device(progress_callback)
            if not success:
                print(f"工具推送失败: {msg}")
                return False
        return True
            
    def _get_npu_load(self):
        """获取NPU占用率（分别统计Core0和Core1）"""
        output = self._execute_command("cat /sys/kernel/debug/rknpu/load")
        print(f"[NPU] 命令输出: {output}")
        if output:
            try:
                # 解析输出，例如: "NPU load:  Core0:  0%, Core1:  0%,"
                import re
                # 提取Core0和Core1的百分比
                core0_match = re.search(r'Core0:\s*([\d.]+)%', output)
                core1_match = re.search(r'Core1:\s*([\d.]+)%', output)
                
                if core0_match and core1_match:
                    core0 = float(core0_match.group(1))
                    core1 = float(core1_match.group(1))
                    avg = (core0 + core1) / 2.0
                    
                    # 保存最新数据
                    self.latest_npu_data = {
                        'core0': core0,
                        'core1': core1,
                        'avg': avg
                    }
                    
                    print(f"[NPU] Core0: {core0:.1f}%, Core1: {core1:.1f}%, 平均: {avg:.1f}%")
                    return avg
            except Exception as e:
                print(f"[NPU] 解析失败: {e}, 原始输出: {output}")
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
        
    def _get_memory_usage(self):
        """获取内存占用率和实际使用量"""
        output = self._execute_command("free -m | grep Mem")
        print(f"[内存] 命令输出: {output}")
        if output:
            try:
                parts = output.split()
                print(f"[内存] 解析结果: {parts}")
                if len(parts) >= 3:
                    total_mb = float(parts[1])
                    used_mb = float(parts[2])
                    usage_percent = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0
                    print(f"[内存] 计算结果: {used_mb}/{total_mb} MB = {usage_percent:.1f}%")
                    # 返回元组：(占用率%, 已使用MB, 总MB)
                    return usage_percent, used_mb, total_mb
            except Exception as e:
                print(f"[内存] 解析失败: {e}, 原始输出: {output}")
        return 0.0, 0.0, 0.0
        
        
    def get_latest_data(self):
        """获取最新的监控数据"""
        return self.latest_data.copy()
        
    def get_history_data(self):
        """获取历史数据"""
        return self.history_data.copy()
        
    def export_data(self, filename="performance_data.csv"):
        """导出历史数据到CSV"""
        import csv
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['时间戳', 'NPU占用(%)', 'CPU占用(%)', '内存占用(%)', 'DDR带宽(MB/s)'])
                
                for i in range(len(self.history_data['timestamps'])):
                    writer.writerow([
                        self.history_data['timestamps'][i],
                        self.history_data['npu_load'][i],
                        self.history_data['cpu_usage'][i],
                        self.history_data['memory_usage'][i],
                        self.history_data['ddr_total'][i]
                    ])
                    
            return True, f"数据已导出到 {filename}"
        except Exception as e:
            return False, f"导出失败: {str(e)}"