# -*- coding: utf-8 -*-
"""
RTMP直播管理模块
功能：控制设备开始/停止RTMP推流
"""

import subprocess
from log_manager import LogManager

log_manager = LogManager()


class RTMPManager:
    """RTMP直播管理器"""
    
    def __init__(self, device_ip=None):
        self.device_ip = device_ip

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

    def _run_device_command(self, command, timeout=30):
        device_id, adb_msg = self._get_usb_adb_device_id()
        if device_id:
            result = subprocess.run(
                ["adb", "-s", device_id, "shell", command],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout,
            )
            if result.returncode == 0:
                return True, "ADB命令执行成功"
            adb_error = (result.stderr or result.stdout or "").strip()
            log_manager.warning(f"[RTMP] ADB命令失败，回退SSH: {adb_error}")
        else:
            log_manager.info(f"[RTMP] ADB不可用，使用SSH: {adb_msg}")

        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(self.device_ip, port=22, username='root', password='', timeout=10)
        try:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8', errors='ignore').strip()
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            if exit_code == 0:
                return True, output or "SSH命令执行成功"
            return False, error_output or output or f"命令退出码 {exit_code}"
        finally:
            ssh.close()
        
    def start_streaming(self, rtmp_url, quality='720p'):
        """
        开始RTMP推流
        
        Args:
            rtmp_url: RTMP服务器地址（如：rtmp://192.168.17.108/live/test）
            quality: 画质质量 ('720p' 或 '1080p')
            
        Returns:
            tuple: (success, message)
        """
        if not self.device_ip:
            error_msg = "未设置设备IP地址"
            log_manager.error(f"[RTMP] {error_msg}")
            return False, error_msg
        
        log_manager.info(f"[RTMP] 开始推流: URL={rtmp_url}, Quality={quality}")
        
        try:
            # 生成live_start.bin文件
            channel = '0' if quality == '720p' else '1'
            
            # 命令1: printf '%-512s' 'rtmp_url' | tr ' ' '\0' > live_start.bin
            cmd1 = f"printf '%-512s' '{rtmp_url}' | tr ' ' '\\0' > live_start.bin"
            
            # 命令2: printf '\x01' >> live_start.bin
            if channel == '0':
                cmd2 = f"printf '\\x00' >> live_start.bin"
            else:
                cmd2 = f"printf '\\x01' >> live_start.bin"
            
            # 命令3: mosquitto_pub -t "IBIR" -f live_start.bin
            cmd3 = f'mosquitto_pub -t "IBIR" -f live_start.bin'
            
            # 组合命令
            full_command = f"{cmd1} && {cmd2} && {cmd3}"
            
            log_manager.info(f"[RTMP] 执行命令: {full_command}")
            
            success, output = self._run_device_command(full_command, timeout=30)
            if success:
                success_msg = f"RTMP推流已启动 ({quality})"
                log_manager.info(f"[RTMP] {success_msg}")
                return True, success_msg
            else:
                error_msg = f"启动推流失败: {output}"
                log_manager.error(f"[RTMP] {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"RTMP推流启动异常: {str(e)}"
            log_manager.error(f"[RTMP] {error_msg}")
            return False, error_msg
    
    def stop_streaming(self):
        """
        停止RTMP推流
        
        Returns:
            tuple: (success, message)
        """
        if not self.device_ip:
            error_msg = "未设置设备IP地址"
            log_manager.error(f"[RTMP] {error_msg}")
            return False, error_msg
        
        log_manager.info("[RTMP] 停止推流")
        
        try:
            # 命令: mosquitto_pub -t "IBKR" -f /oem/usr/bin/1.bin
            command = 'mosquitto_pub -t "IBKR" -f /oem/usr/bin/1.bin'
            
            log_manager.info(f"[RTMP] 执行命令: {command}")
            
            success, output = self._run_device_command(command, timeout=30)
            if success:
                success_msg = "RTMP推流已停止"
                log_manager.info(f"[RTMP] {success_msg}")
                return True, success_msg
            else:
                error_msg = f"停止推流失败: {output}"
                log_manager.error(f"[RTMP] {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"RTMP停止推流异常: {str(e)}"
            log_manager.error(f"[RTMP] {error_msg}")
            return False, error_msg
