# -*- coding: utf-8 -*-
"""
WiFi管理模块
功能：连接WiFi并固化配置
"""

import subprocess
from log_manager import LogManager

log_manager = LogManager()


class WiFiManager:
    """WiFi管理器"""
    
    def __init__(self):
        self.ssh_client = None
        
    def connect_and_persist(self, device_ip=None, ssid='', password='', connection_type='SSH'):
        """连接WiFi并固化配置
        
        Args:
            device_ip: 设备IP地址（SSH必需，ADB可选用于网络ADB，此处按USB连接处理则忽略）
            ssid: WiFi名称
            password: WiFi密码
            connection_type: 连接方式 ('SSH' 或 'ADB')
        """
        log_manager.info(f"[OPERATION] 开始配置WiFi: SSID='{ssid}', Type={connection_type}")
        
        try:
            if connection_type == 'ADB':
                # ADB方式：假设已通过USB连接，不需要IP
                success, msg = self._connect_and_persist_adb(ssid, password)
            else:  # SSH
                # SSH方式：需要IP
                if not device_ip:
                    error_msg = "SSH连接需要提供设备IP地址"
                    log_manager.error(error_msg)
                    return False, error_msg
                success, msg = self._connect_and_persist_ssh(device_ip, ssid, password)
            
            if success:
                log_manager.info(f"[DEVICE] WiFi配置成功: {msg}")
            else:
                log_manager.error(f"[DEVICE] WiFi配置失败: {msg}")
                
            return success, msg
            
        except Exception as e:
            error_msg = f"WiFi配置异常: {str(e)}"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
            
    def _connect_and_persist_ssh(self, device_ip, ssid, password):
        """通过SSH连接配置WiFi"""
        try:
            import paramiko
            
            log_manager.info(f"[DEVICE] 建立SSH连接到 {device_ip}")
            
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(device_ip, port=22, username='root', password='', timeout=10)
            
            # 执行wifi-connect.sh脚本
            command = f"wifi-connect.sh {ssid} {password}"
            log_manager.info(f"[DEVICE] 执行命令: {command}")
            
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=30)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            
            if exit_status == 0 and output.strip():
                log_manager.info(f"[DEVICE] WiFi连接脚本执行成功: {output}")
                
                # 尝试多种固化命令
                persist_commands = [
                    "wifi-save-config",
                    "uci commit wireless",
                    "nmcli connection save",
                    "echo 'WiFi配置已保存'"
                ]
                
                for persist_cmd in persist_commands:
                    log_manager.debug(f"[DEVICE] 尝试固化命令: {persist_cmd}")
                    stdin, stdout, stderr = self.ssh_client.exec_command(persist_cmd, timeout=10)
                    exit_code = stdout.channel.recv_exit_status()
                    if exit_code == 0:
                        log_manager.info(f"[DEVICE] 使用 '{persist_cmd}' 固化配置成功")
                        break
                        
                return True, f"WiFi '{ssid}' 连接成功并已固化配置"
            else:
                error_detail = error if error else "未知错误"
                log_manager.error(f"[DEVICE] WiFi连接失败: {error_detail}")
                return False, f"连接失败: {error_detail}"
                
        except paramiko.AuthenticationException:
            error_msg = "SSH认证失败，请检查设备凭证"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
        except paramiko.SSHException as e:
            error_msg = f"SSH连接错误: {str(e)}"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
        except TimeoutError:
            error_msg = "SSH连接超时，请检查网络连接和设备IP"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"SSH配置WiFi失败: {str(e)}"
            log_manager.error(f"[DEVICE] {error_msg}", exc_info=True)
            return False, error_msg
        finally:
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
                
    def _connect_and_persist_adb(self, ssid, password):
        """通过ADB连接配置WiFi（假设设备已通过USB连接）"""
        try:
            log_manager.info(f"[DEVICE] 检查ADB设备连接...")
            
            # 首先检查是否有ADB设备连接
            result = subprocess.run(
                ['adb', 'devices'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                error_msg = f"ADB命令执行失败: {result.stderr.strip()}"
                log_manager.error(f"[DEVICE] {error_msg}")
                return False, error_msg
            
            # 解析设备列表
            lines = result.stdout.strip().split('\n')
            devices = []
            for line in lines[1:]:  # 跳过第一行标题
                if '\tdevice' in line:
                    device_id = line.split('\t')[0].strip()
                    devices.append(device_id)
            
            if not devices:
                error_msg = "没有检测到ADB设备，请确保：\n1. 设备已通过USB连接\n2. 已启用USB调试模式\n3. 已授权此电脑进行ADB调试"
                log_manager.error(f"[DEVICE] {error_msg}")
                return False, error_msg
            
            # 使用第一个连接的设备
            device_id = devices[0]
            log_manager.info(f"[DEVICE] 找到ADB设备: {device_id}")
            log_manager.info(f"[DEVICE] 执行WiFi连接命令...")
            
            # 执行WiFi连接脚本
            command = f"wifi-connect.sh {ssid} {password}"
            log_manager.info(f"[DEVICE] 执行: {command}")
            
            result = subprocess.run(
                ['adb', '-s', device_id, 'shell', command],
                capture_output=True,
                text=True,
                timeout=90  # WiFi连接可能需要较长时间
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                log_manager.info(f"[DEVICE] WiFi连接成功: {output}")
                
                # 尝试固化配置
                persist_commands = [
                    "wifi-save-config",
                    "uci commit wireless",
                    "nmcli connection save"
                ]
                
                for persist_cmd in persist_commands:
                    log_manager.debug(f"[DEVICE] 尝试固化命令: {persist_cmd}")
                    result = subprocess.run(
                        ['adb', '-s', device_id, 'shell', persist_cmd],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        log_manager.info(f"[DEVICE] 使用 '{persist_cmd}' 固化配置成功")
                        break
                
                return True, f"WiFi '{ssid}' 连接成功（通过ADB USB）"
            else:
                error_detail = result.stderr.strip() if result.stderr else "未知错误"
                log_manager.error(f"[DEVICE] WiFi连接失败: {error_detail}")
                return False, f"连接失败: {error_detail}"
                
        except subprocess.TimeoutExpired:
            error_msg = "ADB命令执行超时，WiFi连接可能需要更长时间（最多90秒）"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
        except FileNotFoundError:
            error_msg = "ADB未安装或不在PATH中，请先安装Android Platform Tools"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"ADB配置WiFi失败: {str(e)}"
            log_manager.error(f"[DEVICE] {error_msg}", exc_info=True)
            return False, error_msg

    def list_available_networks(self, device_ip, connection_type='SSH'):
        """列出可用的WiFi网络
        
        Args:
            device_ip: 设备IP地址
            connection_type: 连接方式 ('SSH' 或 'ADB')
        """
        log_manager.info(f"[OPERATION] 扫描可用WiFi网络: {device_ip} ({connection_type})")
        
        try:
            if connection_type == 'SSH':
                return self._list_networks_ssh(device_ip)
            else:
                return self._list_networks_adb(device_ip)
        except Exception as e:
            error_msg = f"扫描网络失败: {str(e)}"
            log_manager.error(f"[DEVICE] {error_msg}")
            return False, []
            
    def _list_networks_ssh(self, device_ip):
        """通过SSH列出WiFi网络"""
        try:
            import paramiko
            
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(device_ip, port=22, username='root', password='', timeout=10)
            
            command = "iwlist wlan0 scan | grep ESSID"
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=15)
            output = stdout.read().decode('utf-8')
            
            networks = []
            for line in output.strip().split('\n'):
                if 'ESSID' in line:
                    essid = line.split(':')[1].strip('"')
                    if essid:
                        networks.append(essid)
                        
            log_manager.info(f"[DEVICE] 找到 {len(networks)} 个WiFi网络")
            return True, networks
            
        except Exception as e:
            log_manager.error(f"[DEVICE] SSH扫描网络失败: {str(e)}")
            return False, []
        finally:
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
                
    def _list_networks_adb(self, device_ip):
        """通过ADB列出WiFi网络"""
        try:
            # 连接设备
            result = subprocess.run(
                ['adb', 'connect', device_ip],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return False, []
            
            # 扫描网络
            result = subprocess.run(
                ['adb', '-s', device_ip, 'shell', 'iwlist', 'wlan0', 'scan'],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            # 断开连接
            subprocess.run(['adb', 'disconnect', device_ip], capture_output=True, timeout=5)
            
            if result.returncode == 0:
                networks = []
                for line in result.stdout.split('\n'):
                    if 'ESSID' in line:
                        essid = line.split(':')[1].strip('"')
                        if essid:
                            networks.append(essid)
                            
                log_manager.info(f"[DEVICE] ADB扫描找到 {len(networks)} 个WiFi网络")
                return True, networks
            else:
                return False, []
                
        except Exception as e:
            log_manager.error(f"[DEVICE] ADB扫描网络失败: {str(e)}")
            return False, []
            
    def get_current_connection(self, device_ip, connection_type='SSH'):
        """获取当前WiFi连接状态
        
        Args:
            device_ip: 设备IP地址
            connection_type: 连接方式 ('SSH' 或 'ADB')
        """
        try:
            if connection_type == 'SSH':
                return self._get_connection_ssh(device_ip)
            else:
                return self._get_connection_adb(device_ip)
        except Exception as e:
            log_manager.error(f"[DEVICE] 获取连接状态失败: {str(e)}")
            return False, ""
            
    def _get_connection_ssh(self, device_ip):
        """通过SSH获取WiFi连接状态"""
        try:
            import paramiko
            
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(device_ip, port=22, username='root', password='', timeout=10)
            
            command = "iwconfig wlan0"
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=10)
            output = stdout.read().decode('utf-8')
            
            return True, output
            
        except Exception as e:
            log_manager.error(f"[DEVICE] SSH获取WiFi状态失败: {str(e)}")
            return False, str(e)
        finally:
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
                
    def _get_connection_adb(self, device_ip):
        """通过ADB获取WiFi连接状态"""
        try:
            # 连接设备
            result = subprocess.run(
                ['adb', 'connect', device_ip],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return False, "ADB连接失败"
            
            # 获取WiFi状态
            result = subprocess.run(
                ['adb', '-s', device_ip, 'shell', 'iwconfig', 'wlan0'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # 断开连接
            subprocess.run(['adb', 'disconnect', device_ip], capture_output=True, timeout=5)
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
                
        except Exception as e:
            log_manager.error(f"[DEVICE] ADB获取WiFi状态失败: {str(e)}")
            return False, str(e)
