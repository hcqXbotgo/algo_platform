# -*- coding: utf-8 -*-
"""
智能设备管理模块
功能：自动检测设备、配置WiFi、获取IP、切换SSH
"""

import subprocess
import time
import re
from log_manager import LogManager

log_manager = LogManager()


class SmartDeviceManager:
    """智能设备管理器 - 自动化流程"""
    
    def __init__(self):
        self.adb_device_id = None
        self.device_ip = None
        self.ssh_client = None
        
    def auto_connect_and_setup(self):
        """
        自动连接并配置设备（一键完成）
        
        流程：
        1. 检测ADB USB设备
        2. 执行初始化命令（mount、启动SSH等）
        3. 弹出WiFi配置对话框
        4. 通过ADB配置WiFi
        5. 等待并获取设备IP
        6. 切换到SSH连接
        7. 返回设备IP供后续使用
        
        Returns:
            tuple: (success, message, device_ip)
        """
        log_manager.info("[AUTO] 开始自动设备配置流程")
        
        # Step 1: 检测ADB设备
        success, msg = self._detect_adb_device()
        if not success:
            return False, msg, None
        
        # Step 2: 执行初始化命令
        success, msg = self._initialize_device()
        if not success:
            return False, f"设备初始化失败: {msg}", None
        
        # Step 3-5: 需要用户输入WiFi信息
        # 这部分由UI层处理，这里只提供方法
        
        return True, "设备初始化完成，请配置WiFi", self.adb_device_id
    
    def _detect_adb_device(self):
        """检测ADB USB设备"""
        log_manager.info("[AUTO] 检测ADB设备...")
        
        try:
            result = subprocess.run(
                ['adb', 'devices'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                error_msg = f"ADB命令执行失败: {result.stderr.strip()}"
                log_manager.error(f"[AUTO] {error_msg}")
                return False, error_msg
            
            # 解析设备列表
            lines = result.stdout.strip().split('\n')
            devices = []
            for line in lines[1:]:  # 跳过第一行标题
                if '\tdevice' in line or '\t\tdevice' in line:
                    device_id = line.split('\t')[0].strip()
                    if device_id and device_id != 'List of devices attached':
                        devices.append(device_id)
            
            if not devices:
                error_msg = "未检测到ADB设备\n请确保：\n1. 设备已通过USB连接\n2. 已启用USB调试模式\n3. 已授权此电脑进行ADB调试"
                log_manager.error(f"[AUTO] {error_msg}")
                return False, error_msg
            
            # 使用第一个设备
            self.adb_device_id = devices[0]
            log_manager.info(f"[AUTO] 检测到ADB设备: {self.adb_device_id}")
            return True, f"检测到设备: {self.adb_device_id}"
            
        except FileNotFoundError:
            error_msg = "ADB未安装，请先安装Android Platform Tools"
            log_manager.error(f"[AUTO] {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"检测ADB设备失败: {str(e)}"
            log_manager.error(f"[AUTO] {error_msg}")
            return False, error_msg
    
    def _initialize_device(self):
        """执行设备初始化命令"""
        log_manager.info(f"[AUTO] 初始化设备 {self.adb_device_id}...")
        
        init_commands = [
            ("挂载根文件系统", "mount -o remount,rw /"),
            ("挂载OEM分区", "mount -o remount,rw /oem"),
            ("挂载数据分区", "mount -o remount,rw /device_data"),
            ("启动SSH服务", "/etc/init.d/S50sshd start"),
            ("清除root密码", "passwd -d root"),
        ]
        
        for desc, cmd in init_commands:
            log_manager.info(f"[AUTO] 执行{desc}: {cmd}")
            try:
                result = subprocess.run(
                    ['adb', '-s', self.adb_device_id, 'shell', cmd],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                
                if result.returncode == 0:
                    log_manager.info(f"[AUTO] {desc}成功")
                else:
                    # 某些命令可能失败但不影响继续（如SSH已启动）
                    log_manager.warning(f"[AUTO] {desc}返回码: {result.returncode}")
                    
            except subprocess.TimeoutExpired:
                log_manager.warning(f"[AUTO] {desc}超时，继续执行")
            except Exception as e:
                log_manager.warning(f"[AUTO] {desc}异常: {e}")
        
        log_manager.info("[AUTO] 设备初始化完成")
        return True, "初始化命令已执行"
    
    def configure_wifi_via_adb(self, ssid, password):
        """
        通过ADB配置WiFi
        
        Args:
            ssid: WiFi名称
            password: WiFi密码
            
        Returns:
            tuple: (success, message)
        """
        log_manager.info(f"[AUTO] 通过ADB配置WiFi: SSID='{ssid}'")
        
        if not self.adb_device_id:
            error_msg = "ADB设备未连接"
            log_manager.error(f"[AUTO] {error_msg}")
            return False, error_msg
        
        try:
            # 执行WiFi连接命令
            command = f"wifi-connect.sh {ssid} {password}"
            log_manager.info(f"[AUTO] 执行: {command}")
            
            result = subprocess.run(
                ['adb', '-s', self.adb_device_id, 'shell', command],
                capture_output=True,
                text=True,
                timeout=90  # WiFi连接可能需要较长时间
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                log_manager.info(f"[AUTO] WiFi连接成功: {output}")
                
                # 等待几秒让网络稳定
                log_manager.info("[AUTO] 等待网络稳定...")
                time.sleep(5)
                
                return True, f"WiFi '{ssid}' 连接成功"
            else:
                error_detail = result.stderr.strip() if result.stderr else "未知错误"
                log_manager.error(f"[AUTO] WiFi连接失败: {error_detail}")
                return False, f"连接失败: {error_detail}"
                
        except subprocess.TimeoutExpired:
            error_msg = "WiFi连接超时，请检查SSID和密码是否正确"
            log_manager.error(f"[AUTO] {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"WiFi配置失败: {str(e)}"
            log_manager.error(f"[AUTO] {error_msg}")
            return False, error_msg
    
    def get_device_ip(self):
        """
        获取设备IP地址
        
        Returns:
            str: IP地址或None
        """
        log_manager.info("[AUTO] 获取设备IP地址...")
        
        if not self.adb_device_id:
            return None
        
        try:
            # 尝试多种方式获取IP
            ip_commands = [
                "ip addr show wlan0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1",
                "ifconfig wlan0 | grep 'inet addr:' | cut -d: -f2 | awk '{print $1}'",
                "hostname -I | awk '{print $1}'",
            ]
            
            for cmd in ip_commands:
                log_manager.debug(f"[AUTO] 尝试命令: {cmd}")
                result = subprocess.run(
                    ['adb', '-s', self.adb_device_id, 'shell', cmd],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    ip = result.stdout.strip().split('\n')[-1].strip()
                    # 验证IP格式
                    if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', ip):
                        self.device_ip = ip
                        log_manager.info(f"[AUTO] 获取到设备IP: {ip}")
                        return ip
            
            log_manager.warning("[AUTO] 未能获取到有效的IP地址")
            return None
            
        except Exception as e:
            log_manager.error(f"[AUTO] 获取IP失败: {e}")
            return None
    
    def test_ssh_connection(self, ip=None):
        """
        测试SSH连接
        
        Args:
            ip: IP地址，如果为None则使用已保存的device_ip
            
        Returns:
            tuple: (success, message)
        """
        if ip:
            self.device_ip = ip
        
        if not self.device_ip:
            return False, "没有可用的IP地址"
        
        log_manager.info(f"[AUTO] 测试SSH连接到 {self.device_ip}...")
        
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.device_ip, 
                port=22, 
                username='root', 
                password='', 
                timeout=10
            )
            
            # 测试基本命令
            stdin, stdout, stderr = ssh.exec_command("echo 'SSH connected'")
            output = stdout.read().decode('utf-8').strip()
            
            ssh.close()
            
            if output == "SSH connected":
                self.ssh_client = None  # 关闭测试连接
                log_manager.info(f"[AUTO] SSH连接成功: {self.device_ip}")
                return True, f"SSH连接成功: {self.device_ip}"
            else:
                return False, "SSH测试失败"
                
        except Exception as e:
            log_manager.error(f"[AUTO] SSH连接失败: {e}")
            return False, f"SSH连接失败: {str(e)}"
    
    def get_rtsp_urls(self):
        """
        根据设备IP生成RTSP推流地址
        
        Returns:
            tuple: (rtsp_url_0, rtsp_url_1) 或 (None, None)
        """
        if not self.device_ip:
            return None, None
        
        rtsp_0 = f"rtsp://{self.device_ip}/live/0"
        rtsp_1 = f"rtsp://{self.device_ip}/live/1"
        
        log_manager.info(f"[AUTO] 生成RTSP地址:\n  Channel 0: {rtsp_0}\n  Channel 1: {rtsp_1}")
        
        return rtsp_0, rtsp_1
    
    def full_auto_setup(self, wifi_ssid, wifi_password):
        """
        完整自动配置流程（一键配置）
        
        Args:
            wifi_ssid: WiFi名称
            wifi_password: WiFi密码
            
        Returns:
            tuple: (success, message, device_ip, rtsp_0, rtsp_1)
        """
        log_manager.info("=" * 60)
        log_manager.info("[AUTO] 开始完整自动配置流程")
        log_manager.info("=" * 60)
        
        # Step 1: 检测ADB设备
        success, msg = self._detect_adb_device()
        if not success:
            return False, msg, None, None, None
        
        # Step 2: 初始化设备
        success, msg = self._initialize_device()
        if not success:
            return False, f"初始化失败: {msg}", None, None, None
        
        # Step 3: 配置WiFi
        success, msg = self.configure_wifi_via_adb(wifi_ssid, wifi_password)
        if not success:
            return False, f"WiFi配置失败: {msg}", None, None, None
        
        # Step 4: 获取IP
        max_retries = 5
        for attempt in range(max_retries):
            log_manager.info(f"[AUTO] 尝试获取IP ({attempt + 1}/{max_retries})...")
            ip = self.get_device_ip()
            
            if ip:
                break
            
            log_manager.info(f"[AUTO] 第{attempt + 1}次尝试失败，等待5秒后重试...")
            time.sleep(5)
        
        if not ip:
            return False, "无法获取设备IP地址，请检查WiFi连接", None, None, None
        
        # Step 5: 测试SSH
        success, msg = self.test_ssh_connection(ip)
        if not success:
            return False, f"SSH连接测试失败: {msg}", ip, None, None
        
        # Step 6: 生成RTSP地址
        rtsp_0, rtsp_1 = self.get_rtsp_urls()
        
        log_manager.info("=" * 60)
        log_manager.info("[AUTO] 配置完成！")
        log_manager.info(f"[AUTO] 设备IP: {self.device_ip}")
        log_manager.info(f"[AUTO] RTSP 0: {rtsp_0}")
        log_manager.info(f"[AUTO] RTSP 1: {rtsp_1}")
        log_manager.info("=" * 60)
        
        return True, "设备配置完成！", self.device_ip, rtsp_0, rtsp_1
