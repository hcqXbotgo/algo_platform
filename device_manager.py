# -*- coding: utf-8 -*-
"""
设备管理模块
功能：SSH/ADB连接、文件推送、进程管理
"""

import paramiko
import subprocess
import os
import time
import re
import json
import shlex
from datetime import datetime
from log_manager import log_manager


def connect_ssh_with_retry(
    hostname,
    username='root',
    password='',
    port=22,
    retries=4,
    timeout=2.0,
    banner_timeout=1.5,
    auth_timeout=2.5,
    channel_timeout=3.0,
    retry_delay=0.5,
):
    """快速重试 SSH 连接，适合设备刚开机时 SSH banner 还未准备好的场景。"""
    last_error = None

    for attempt in range(1, retries + 1):
        ssh_client = None
        start_time = time.time()

        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                hostname,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
                banner_timeout=banner_timeout,
                auth_timeout=auth_timeout,
                channel_timeout=channel_timeout,
                allow_agent=False,
                look_for_keys=False,
            )

            elapsed = time.time() - start_time
            log_manager.info(
                f"[DEVICE] SSH连接成功: {hostname} (尝试 {attempt}/{retries}, {elapsed:.2f}s)"
            )
            return ssh_client, True, "SSH连接成功"

        except paramiko.AuthenticationException as e:
            if ssh_client:
                ssh_client.close()
            log_manager.error(f"[DEVICE] SSH认证失败: {str(e)}")
            return None, False, f"SSH认证失败: {str(e)}"

        except Exception as e:
            last_error = e
            elapsed = time.time() - start_time
            if ssh_client:
                ssh_client.close()

            log_manager.warning(
                f"[DEVICE] SSH连接尝试 {attempt}/{retries} 失败 ({elapsed:.2f}s): {str(e)}"
            )

            if attempt < retries:
                sleep_time = min(retry_delay * attempt, 1.0)
                time.sleep(sleep_time)

    return None, False, f"SSH连接失败: {str(last_error)}"


def _run_subprocess_text(command, timeout=10):
    """Run a subprocess command and decode text output consistently."""
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
        timeout=timeout,
    )


class DeviceManager:
    """设备管理器，处理SSH和ADB连接"""
    
    def __init__(self):
        self.ssh_client = None
        self.current_device_ip = None  # 保存当前连接的设备IP
        self.current_adb_device_id = None
        self.connection_mode = None
        
    def connect_ssh(
        self,
        hostname,
        username='root',
        password='',
        port=22,
        retries=4,
        timeout=2.0,
        banner_timeout=1.5,
        auth_timeout=2.5,
        channel_timeout=3.0,
        retry_delay=0.5,
        auto_start_ssh=True,
    ):
        """建立SSH连接"""
        try:
            self.close_ssh()
            self.ssh_client, success, msg = connect_ssh_with_retry(
                hostname,
                username=username,
                password=password,
                port=port,
                retries=retries,
                timeout=timeout,
                banner_timeout=banner_timeout,
                auth_timeout=auth_timeout,
                channel_timeout=channel_timeout,
                retry_delay=retry_delay,
            )
            if not success:
                self.ssh_client = None
                if auto_start_ssh:
                    log_manager.warning(f"[DEVICE] SSH连接失败，尝试通过ADB启动SSH服务: {msg}")
                    adb_success, adb_msg = self.ensure_ssh_service_via_adb()
                    if adb_success:
                        log_manager.info("[DEVICE] ADB启动SSH服务完成，重新尝试SSH连接")
                        self.ssh_client, success, retry_msg = connect_ssh_with_retry(
                            hostname,
                            username=username,
                            password=password,
                            port=port,
                            retries=3,
                            timeout=timeout,
                            banner_timeout=banner_timeout,
                            auth_timeout=auth_timeout,
                            channel_timeout=channel_timeout,
                            retry_delay=retry_delay,
                        )
                        if success:
                            self.current_device_ip = hostname
                            self.connection_mode = "ssh"
                            return True, "SSH连接成功"
                        self.ssh_client = None
                        return False, f"{retry_msg}；已尝试ADB启动SSH服务: {adb_msg}"
                    return False, f"{msg}；ADB启动SSH服务失败: {adb_msg}"
                return False, msg
            self.current_device_ip = hostname  # 保存设备IP
            self.connection_mode = "ssh"
            return True, "SSH连接成功"
        except Exception as e:
            return False, f"SSH连接失败: {str(e)}"

    def get_adb_device_id(self):
        """获取当前可用的USB ADB设备ID。"""
        try:
            result = _run_subprocess_text(['adb', 'devices'], timeout=5)
        except FileNotFoundError:
            return None, "ADB未安装或未添加到PATH"
        except subprocess.TimeoutExpired:
            return None, "ADB设备检测超时"
        except Exception as e:
            return None, f"ADB设备检测失败: {str(e)}"

        if result.returncode != 0:
            return None, f"ADB命令执行失败: {result.stderr.strip()}"

        for line in result.stdout.strip().splitlines()[1:]:
            if '\tdevice' not in line:
                continue
            device_id = line.split('\t')[0].strip()
            if device_id:
                return device_id, f"检测到ADB设备: {device_id}"

        return None, "未检测到可用ADB设备"

    def is_adb_device_connected(self, device_id=None, timeout=1.5):
        """Return whether the expected USB ADB device is still connected."""
        expected_id = device_id or self.current_adb_device_id
        if not expected_id:
            return False, "未记录ADB设备ID"

        try:
            result = _run_subprocess_text(['adb', 'devices'], timeout=timeout)
        except FileNotFoundError:
            return False, "ADB未安装或未加入PATH"
        except subprocess.TimeoutExpired:
            return False, "ADB设备检测超时"
        except Exception as e:
            return False, f"ADB设备检测失败: {str(e)}"

        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "ADB命令执行失败").strip()

        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == expected_id and parts[1] == "device":
                return True, f"ADB设备在线: {expected_id}"
        return False, f"ADB设备已断开: {expected_id}"

    def connect_adb(self):
        """Connect by USB ADB only; SSH is not required for wired mode."""
        device_id, msg = self.get_adb_device_id()
        if not device_id:
            self.current_adb_device_id = None
            self.connection_mode = None
            return False, msg, None

        self.current_adb_device_id = device_id
        self.connection_mode = "adb"
        remount_success, remount_msg = self.remount_partitions_via_adb(device_id)
        device_ip = self.get_current_device_ip_via_adb()
        if device_ip:
            self.current_device_ip = device_ip
        if remount_success:
            log_manager.info(f"[ADB] USB ADB connected: {device_id}, ip={device_ip or 'N/A'}, {remount_msg}")
        else:
            log_manager.warning(f"[ADB] USB ADB connected but remount is incomplete: {remount_msg}")
        return True, f"ADB连接成功: {device_id}\n{remount_msg}", device_ip

    def run_adb_shell_command(self, command, device_id=None, timeout=15):
        """通过ADB执行shell命令。"""
        if not device_id:
            device_id, msg = self.get_adb_device_id()
            if not device_id:
                return False, msg

        try:
            result = _run_subprocess_text(
                ['adb', '-s', device_id, 'shell', command],
                timeout=timeout,
            )
            output = (result.stdout or '').strip()
            error = (result.stderr or '').strip()
            if result.returncode == 0:
                return True, output
            return False, error or output or f"返回码: {result.returncode}"
        except subprocess.TimeoutExpired:
            return False, f"ADB命令超时: {command}"
        except FileNotFoundError:
            return False, "ADB未安装或未添加到PATH"
        except Exception as e:
            return False, f"ADB命令异常: {str(e)}"

    def _get_adb_file_size(self, device_id, remote_path):
        """Return remote file size over ADB without relying on stat(1)."""
        quoted = shlex.quote(remote_path)
        commands = [
            f"wc -c < {quoted}",
            f"ls -ln {quoted} 2>/dev/null | awk '{{print $5}}'",
            f"busybox stat -c %s {quoted} 2>/dev/null",
            f"toybox stat -c %s {quoted} 2>/dev/null",
        ]
        last_output = ""
        for command in commands:
            success, output = self.run_adb_shell_command(command, device_id=device_id, timeout=10)
            last_output = output
            if not success or not output:
                continue
            match = re.search(r"\d+", str(output).strip().splitlines()[-1])
            if match:
                try:
                    return int(match.group(0)), output
                except ValueError:
                    pass
        return None, last_output or "无法获取远端文件大小"

    def _adb_process_running(self, device_id, process_name):
        safe_name = shlex.quote(process_name)
        success, output = self.run_adb_shell_command(
            f"pidof {safe_name} 2>/dev/null",
            device_id=device_id,
            timeout=5,
        )
        if success and output.strip():
            return True, output

        ps_command = (
            "ps 2>/dev/null | awk "
            + shlex.quote(
                "NR>1 && $0 !~ /awk/ && $0 !~ /grep/ && "
                "$0 !~ /sh -c/ && $0 !~ /bash -c/ && "
                f"$0 ~ /(^|[\\/ ]){process_name}([ ]|$)/ {{print}}"
            )
        )
        success, output = self.run_adb_shell_command(ps_command, device_id=device_id, timeout=5)
        return bool(success and output.strip()), output

    def remount_partitions_via_adb(self, device_id=None):
        """Remount known writable partitions after USB ADB connects."""
        if not device_id:
            device_id, msg = self.get_adb_device_id()
            if not device_id:
                return False, msg

        partitions = ["/", "/oem", "/device_data"]
        messages = []
        all_ok = True

        for partition in partitions:
            quoted = shlex.quote(partition)
            command = (
                f"if [ ! -e {quoted} ]; then echo 'skip: {partition} not found'; exit 0; fi; "
                f"if ! awk -v p={quoted} '$2==p {{found=1}} END {{exit found ? 0 : 1}}' /proc/mounts; "
                f"then echo 'skip: {partition} not mounted'; exit 0; fi; "
                f"mount -o remount,rw {quoted} 2>/dev/null || mount -o rw,remount {quoted} 2>/dev/null || true; "
                f"opts=$(awk -v p={quoted} '$2==p {{print $4; exit}}' /proc/mounts); "
                "if echo \"$opts\" | grep -qw rw; then echo \"$opts\"; exit 0; fi; "
                "echo \"${opts:-unknown}\"; exit 1"
            )
            success, output = self.run_adb_shell_command(command, device_id=device_id, timeout=10)
            output = (output or "").strip()
            if success and output.startswith("skip:"):
                messages.append(output)
                log_manager.info(f"[ADB] remount skipped: {output}")
            elif success:
                messages.append(f"{partition}: rw")
                log_manager.info(f"[ADB] remount rw ok: {partition} ({output})")
            else:
                all_ok = False
                detail = output or "unknown error"
                messages.append(f"{partition}: remount failed ({detail})")
                log_manager.warning(f"[ADB] remount rw failed: {partition}, {detail}")

        return all_ok, "分区读写挂载: " + "; ".join(messages)

    def ensure_ssh_service_via_adb(self):
        """通过ADB挂载分区、启动sshd，并清除root密码。"""
        device_id, msg = self.get_adb_device_id()
        if not device_id:
            log_manager.warning(f"[ADB] 无法通过ADB启动SSH服务: {msg}")
            return False, msg

        remount_success, remount_msg = self.remount_partitions_via_adb(device_id)
        messages = [remount_msg]

        init_commands = [
            ("启动SSH服务", "/etc/init.d/S50sshd start"),
            ("清除root密码", "passwd -d root"),
        ]
        for desc, command in init_commands:
            log_manager.info(f"[ADB] {desc}: {command}")
            success, output = self.run_adb_shell_command(command, device_id=device_id, timeout=15)
            if success:
                messages.append(f"{desc}成功")
                log_manager.info(f"[ADB] {desc}成功")
            else:
                messages.append(f"{desc}返回: {output}")
                log_manager.warning(f"[ADB] {desc}返回: {output}")

        time.sleep(0.8)
        return remount_success, "；".join(messages)

    def get_current_device_ip_via_adb(self):
        """通过ADB获取设备当前WiFi IP。"""
        device_id, msg = self.get_adb_device_id()
        if not device_id:
            log_manager.info(f"[ADB] {msg}")
            return None

        ip_commands = [
            "ip addr show wlan0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1",
            "ifconfig wlan0 | grep 'inet addr:' | cut -d: -f2 | awk '{print $1}'",
            "hostname -I | awk '{print $1}'",
        ]

        for command in ip_commands:
            success, output = self.run_adb_shell_command(command, device_id=device_id, timeout=2)
            if not success or not output:
                continue
            ip = output.splitlines()[-1].strip()
            if re.match(r'\d{1,3}(?:\.\d{1,3}){3}', ip):
                log_manager.info(f"[ADB] 成功获取设备IP: {ip}")
                return ip

        log_manager.warning("[ADB] 未能获取到有效的IP地址")
        return None
            
    def _usb_adb_available(self):
        device_id, msg = self.get_adb_device_id()
        if device_id:
            return device_id
        return None

    def execute_ssh_command(self, command, timeout=30):
        """执行设备 shell 命令：USB ADB 优先，失败后按需回退 SSH。"""
        device_id, adb_msg = self.get_adb_device_id()
        if device_id:
            success, output = self.run_adb_shell_command(
                command,
                device_id=device_id,
                timeout=timeout,
            )
            if success:
                self.current_adb_device_id = device_id
                self.connection_mode = "adb"
                return True, output
            log_manager.warning(f"[ADB] shell command failed, command={command}, output={output}")
        else:
            log_manager.info(f"[ADB] shell command skipped: {adb_msg}")

        # Try SSH when ADB is unavailable or an ADB shell command fails.
        current_ip = str(self.current_device_ip or "").strip()
        can_try_ssh = bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", current_ip))
        if not self.ssh_client and can_try_ssh:
            log_manager.info(f"[DEVICE] SSH连接已关闭，正在自动重连到 {current_ip}...")
            success, msg = self.connect_ssh(current_ip)
            if not success:
                log_manager.error(f"[DEVICE] 自动重连失败: {msg}")
                return False, f"未建立SSH连接且自动重连失败: {msg}"
            log_manager.info(f"[DEVICE] 自动重连成功")
        
        if not self.ssh_client:
            return False, "未建立SSH连接"
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            
            if exit_status == 0:
                return True, output
            else:
                return False, error
        except Exception as e:
            return False, f"命令执行失败: {str(e)}"
            
    def close_ssh(self):
        """关闭SSH连接"""
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None
    
    def scp_download_file(self, remote_path, local_path):
        """从设备下载文件"""
        if not self.ssh_client:
            return False, "未建立SSH连接"
        
        try:
            log_manager.info(f"[SCP] 正在下载文件: {remote_path} -> {local_path}")
            sftp = self.ssh_client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            
            # 验证文件是否下载成功
            if os.path.exists(local_path):
                file_size = os.path.getsize(local_path)
                log_manager.info(f"[SCP] 文件下载成功，大小: {file_size} 字节")
                return True, f"下载成功，文件大小: {file_size} 字节"
            else:
                return False, "文件下载失败，本地文件不存在"
                
        except Exception as e:
            log_manager.error(f"[SCP] 文件下载失败: {str(e)}")
            return False, f"文件下载失败: {str(e)}"
            
    def push_model(self, model_file, device_ip, connection_type='SSH'):
        """推送模型文件到设备"""
        try:
            remote_path = "/oem/usr/models/"

            # Always try wired USB ADB first. If the cable is not connected or
            # adb fails, fall back to the existing SSH/SFTP path.
            success, msg = self._push_via_adb(model_file, device_ip, remote_path)
            if not success:
                log_manager.warning(f"[ADB] model push unavailable, fallback to SSH: {msg}")
                success, msg = self._push_via_scp(model_file, device_ip, remote_path)
                
            if success:
                # 推送成功后，可能需要更新配置文件
                return True, f"模型已推送到 {remote_path}"
            else:
                return False, msg
                
        except Exception as e:
            return False, f"推送失败: {str(e)}"
            
    def _push_via_scp(self, local_file, hostname, remote_path):
        """通过SCP推送文件"""
        try:
            log_manager.info(f"[SCP] 开始连接设备 {hostname}...")
            
            # 创建SSH客户端并设置自动接受主机密钥（避免known_hosts冲突）
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 连接到设备
            ssh_client.connect(hostname, port=22, username='root', password='')
            
            # 从SSH客户端获取SFTP客户端
            sftp = ssh_client.open_sftp()
            
            # 确保远程目录存在
            log_manager.info(f"[SCP] 检查远程目录: {remote_path}")
            try:
                # 尝试列出目录，如果失败则创建
                sftp.listdir(remote_path)
                log_manager.info(f"[SCP] 远程目录已存在")
            except FileNotFoundError:
                # 目录不存在，递归创建
                log_manager.warning(f"[SCP] 远程目录不存在，正在创建: {remote_path}")
                self._mkdirs(sftp, remote_path)
                log_manager.info(f"[SCP] 远程目录创建成功")

            remote_full_path = os.path.join(remote_path, os.path.basename(local_file))
            
            # 上传文件
            file_size = os.path.getsize(local_file)
            log_manager.info(f"[SCP] 开始上传文件: {os.path.basename(local_file)} ({file_size / 1024 / 1024:.2f} MB)")
            sftp.put(local_file, remote_full_path)
            
            # 验证文件是否成功上传
            if sftp.stat(remote_full_path):
                uploaded_size = sftp.stat(remote_full_path).st_size
                log_manager.info(f"[SCP] 文件上传成功并验证通过: {remote_full_path} ({uploaded_size / 1024 / 1024:.2f} MB)")
                sftp.close()
                ssh_client.close()
                return True, f"文件已上传: {remote_full_path}"
            else:
                log_manager.error(f"[SCP] 文件上传后验证失败: {remote_full_path}")
                sftp.close()
                ssh_client.close()
                return False, "文件上传后验证失败"
                
        except Exception as e:
            error_msg = str(e)
            log_manager.error(f"[SCP] 上传异常: {error_msg}", exc_info=True)
            return False, f"SCP上传失败: {error_msg}"

    def _mkdirs(self, sftp, remote_dir):
        """递归创建远程目录"""
        parts = remote_dir.split('/')
        current_path = ''
        
        for part in parts:
            if not part:
                continue
            current_path += '/' + part
            try:
                sftp.mkdir(current_path)
            except IOError:
                # 目录已存在或无法创建，继续
                pass

    def _push_via_adb(self, local_file, device_ip, remote_path):
        """通过ADB推送文件"""
        try:
            device_id, msg = self.get_adb_device_id()
            if not device_id:
                return False, msg

            remote_path = remote_path.replace("\\", "/")
            if not remote_path.endswith("/"):
                remote_path += "/"
            remote_full_path = f"{remote_path}{os.path.basename(local_file)}"
            file_size = os.path.getsize(local_file)

            if remote_path.startswith("/oem"):
                self.run_adb_shell_command("mount -o remount,rw /oem 2>/dev/null || true", device_id=device_id, timeout=10)
            mkdir_ok, mkdir_msg = self.run_adb_shell_command(
                f"mkdir -p {shlex.quote(remote_path.rstrip('/'))}",
                device_id=device_id,
                timeout=10,
            )
            if not mkdir_ok:
                return False, f"ADB创建远端目录失败: {mkdir_msg}"

            result = _run_subprocess_text(
                ['adb', '-s', device_id, 'push', local_file, remote_full_path],
                timeout=300,
            )
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode != 0:
                return False, error or output or f"adb push返回码 {result.returncode}"

            uploaded_size, stat_output = self._get_adb_file_size(device_id, remote_full_path)
            if uploaded_size is not None and uploaded_size != file_size:
                return False, f"ADB上传校验失败: 本地={file_size}, 远端={uploaded_size}"
            if uploaded_size is None:
                log_manager.warning(f"[ADB] file size check skipped: {stat_output}")

            self.current_adb_device_id = device_id
            self.connection_mode = "adb"
            return True, f"文件已通过USB ADB上传: {remote_full_path}"
        except Exception as e:
            return False, f"ADB上传失败: {str(e)}"

    def _pull_via_adb(self, remote_path, local_path, progress_callback=None):
        """Pull a device file by USB ADB. Returns (success, message)."""
        try:
            device_id, msg = self.get_adb_device_id()
            if not device_id:
                return False, msg

            total = 0
            remote_size, stat_output = self._get_adb_file_size(device_id, remote_path)
            if remote_size is not None:
                total = remote_size
            else:
                log_manager.warning(f"[ADB] remote file size unavailable: {stat_output}")

            local_dir = os.path.dirname(os.path.abspath(local_path))
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)
            if progress_callback:
                progress_callback(0, total)

            result = _run_subprocess_text(
                ['adb', '-s', device_id, 'pull', remote_path, local_path],
                timeout=600,
            )
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode != 0:
                if os.path.exists(local_path):
                    os.remove(local_path)
                return False, error or output or f"adb pull返回码 {result.returncode}"

            if not os.path.exists(local_path):
                return False, "ADB下载失败: 本地文件不存在"
            local_size = os.path.getsize(local_path)
            if total and local_size != total:
                if os.path.exists(local_path):
                    os.remove(local_path)
                return False, f"ADB下载校验失败: 本地={local_size}, 远端={total}"

            if progress_callback:
                progress_callback(local_size, total or local_size)
            self.current_adb_device_id = device_id
            self.connection_mode = "adb"
            return True, local_path
        except Exception as e:
            try:
                if local_path and os.path.exists(local_path):
                    os.remove(local_path)
            except OSError:
                pass
            return False, f"ADB下载失败: {str(e)}"
            
    def push_config(self, config_file, device_ip):
        """推送配置文件到设备"""
        try:
            remote_path = "/oem/usr/models/"
            remote_full_path = os.path.join(remote_path, os.path.basename(config_file))

            adb_success, adb_msg = self._push_via_adb(config_file, device_ip, remote_path)
            if adb_success:
                return True, f"配置已通过USB ADB推送到 {remote_full_path}"
            log_manager.warning(f"[ADB] config push unavailable, fallback to SSH: {adb_msg}")
            
            # 使用SSHClient推送
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='')
            
            sftp = ssh_client.open_sftp()
            sftp.put(config_file, remote_full_path)
            
            sftp.close()
            ssh_client.close()
            
            return True, f"配置已推送到 {remote_full_path}"
        except Exception as e:
            return False, f"配置推送失败: {str(e)}"

    def _restart_media_process_via_adb(self, device_id, extra_env=None):
        log_dir = "/userdata/logs"
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        log_file = f"{log_dir}/multi_media-{timestamp}-redir.log"

        commands = [
            "killall multi_media 2>/dev/null || true",
            "for pid in $(pidof multi_media 2>/dev/null); do kill -TERM \"$pid\" 2>/dev/null || true; done",
            "sleep 2",
            "for pid in $(pidof multi_media 2>/dev/null); do kill -KILL \"$pid\" 2>/dev/null || true; done",
            f"mkdir -p {log_dir}",
            "mkdir -p /userdata/coredump",
            "rm -f /tmp/multi_media.pid",
        ]
        for command in commands:
            self.run_adb_shell_command(command, device_id=device_id, timeout=10)

        env_parts = [
            "export TARGET_DIR=/oem",
            "export LD_LIBRARY_PATH=/oem/usr/lib:/lib:${LD_LIBRARY_PATH:-}",
            "export PATH=/oem/usr/bin:/bin:${PATH:-}",
            "ulimit -c unlimited",
            "echo '/userdata/coredump/core-%e-%p-%t' > /proc/sys/kernel/core_pattern 2>/dev/null || true",
        ]
        for key, value in (extra_env or {}).items():
            env_parts.append(f"export {key}={shlex.quote(str(value))}")
        start_command = (
            "; ".join(env_parts) + "; "
            f"cd /oem/usr/bin || exit 1; "
            "start-stop-daemon -S -b -m -p /tmp/multi_media.pid "
            f"-x /oem/usr/bin/multi_media > {shlex.quote(log_file)} 2>&1"
        )
        ok, output = self.run_adb_shell_command(start_command, device_id=device_id, timeout=10)
        if not ok:
            return False, f"ADB启动multi_media失败: {output}"

        last_output = ""
        for _ in range(24):
            time.sleep(0.5)
            running, output = self._adb_process_running(device_id, "multi_media")
            last_output = output
            if running:
                return True, f"multi_media已通过ADB重启，日志: {log_file}"

        debug_command = (
            f"echo '--- redir: {log_file} ---'; "
            f"tail -n 80 {shlex.quote(log_file)} 2>/dev/null || true; "
            "latest=$(ls -1t /userdata/logs/multi_media*.log /userdata/logs/multi_media*-redir.log 2>/dev/null | head -1); "
            "if [ -n \"$latest\" ]; then echo \"--- latest: $latest ---\"; tail -n 120 \"$latest\" 2>/dev/null || true; fi; "
            "echo '--- ps ---'; ps 2>/dev/null | grep multi_media | grep -v grep || true; "
            "echo '--- coredump ---'; ls -lt /userdata/coredump 2>/dev/null | head -5 || true"
        )
        debug_ok, debug_output = self.run_adb_shell_command(
            debug_command,
            device_id=device_id,
            timeout=10,
        )
        detail = debug_output.strip() if debug_ok and debug_output.strip() else last_output
        return False, f"ADB启动后未检测到multi_media进程。日志尾部: {detail}"

    def _replace_runtime_component_via_adb(self, local_file, remote_dir, remote_name, label):
        device_id, msg = self.get_adb_device_id()
        if not device_id:
            return False, msg

        remote_full_path = f"{remote_dir}/{remote_name}"
        local_size = os.path.getsize(local_file)
        pre_commands = [
            "mount -o remount,rw /oem 2>/dev/null || true",
            f"mkdir -p {shlex.quote(remote_dir)}",
            "killall multi_media 2>/dev/null || true",
            "for pid in $(pidof multi_media 2>/dev/null); do kill -TERM \"$pid\" 2>/dev/null || true; done",
            "sleep 2",
            "for pid in $(pidof multi_media 2>/dev/null); do kill -KILL \"$pid\" 2>/dev/null || true; done",
        ]
        for command in pre_commands:
            ok, output = self.run_adb_shell_command(command, device_id=device_id, timeout=15)
            if not ok and command.startswith("mkdir"):
                return False, f"ADB创建远端目录失败: {output}"

        result = _run_subprocess_text(
            ['adb', '-s', device_id, 'push', local_file, remote_full_path],
            timeout=300,
        )
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0:
            return False, error or output or f"adb push返回码 {result.returncode}"

        remote_size, stat_output = self._get_adb_file_size(device_id, remote_full_path)
        if remote_size is not None and remote_size != local_size:
            return False, f"ADB上传校验失败: 本地={local_size}, 远端={remote_size}"
        if remote_size is None:
            log_manager.warning(f"[ADB] runtime file size check skipped: {stat_output}")

        ok, chmod_output = self.run_adb_shell_command(
            f"chmod 755 {shlex.quote(remote_full_path)} && sync",
            device_id=device_id,
            timeout=20,
        )
        if not ok:
            return False, f"ADB chmod失败: {chmod_output}"

        restart_success, restart_msg = self._restart_media_process_via_adb(device_id)
        if not restart_success:
            return False, f"{label}已通过ADB替换到 {remote_full_path}，但multi_media重启失败: {restart_msg}"

        self.current_adb_device_id = device_id
        self.connection_mode = "adb"
        return True, f"{label}已通过USB ADB替换到 {remote_full_path}，chmod 755完成，{restart_msg}"

    def publish_track_command_via_adb(self, track_id):
        """Publish the one-byte track command from inside the device via ADB."""
        try:
            track_id = int(track_id)
            if track_id < 0 or track_id > 255:
                return False, f"追踪ID超出1字节范围: {track_id}"

            device_id, msg = self.get_adb_device_id()
            if not device_id:
                return False, msg

            tool_ok, tool_output = self.run_adb_shell_command(
                "command -v mosquitto_pub || which mosquitto_pub",
                device_id=device_id,
                timeout=5,
            )
            if not tool_ok or not tool_output.strip():
                return False, "设备端未找到 mosquitto_pub，无法通过ADB本机发布MQTT"

            temp_file = f"/tmp/track_cmd_{int(time.time() * 1000)}.bin"
            payload = f"\\{track_id:03o}"
            command = (
                f"printf '{payload}' > {shlex.quote(temp_file)} && "
                f"mosquitto_pub -h 127.0.0.1 -t track -f {shlex.quote(temp_file)}; "
                "rc=$?; "
                f"rm -f {shlex.quote(temp_file)}; "
                "exit $rc"
            )
            success, output = self.run_adb_shell_command(
                command,
                device_id=device_id,
                timeout=10,
            )
            if success:
                self.current_adb_device_id = device_id
                self.connection_mode = "adb"
                return True, f"已通过ADB在设备本机发送追踪指令，ID: {track_id}"
            return False, f"ADB本机MQTT发送失败: {output}"
        except Exception as e:
            return False, f"ADB本机MQTT发送异常: {str(e)}"

    def replace_runtime_component(self, local_file, device_ip, component_type):
        """替换设备运行时组件，chmod 后重启 multi_media。"""
        if not local_file or not os.path.isfile(local_file):
            return False, "请选择有效的本地文件"

        if component_type == "multi_media":
            remote_dir = "/oem/usr/bin"
            remote_name = "multi_media"
            label = "multi_media程序"
        elif component_type == "sdk":
            remote_dir = "/oem/usr/lib"
            remote_name = os.path.basename(local_file)
            label = "算法库SDK"
        else:
            return False, f"未知组件类型: {component_type}"

        remote_full_path = f"{remote_dir}/{remote_name}"

        adb_success, adb_msg = self._replace_runtime_component_via_adb(
            local_file,
            remote_dir,
            remote_name,
            label,
        )
        if adb_success:
            return True, adb_msg
        if self._usb_adb_available():
            return False, adb_msg
        log_manager.warning(f"[ADB] runtime component replace unavailable, fallback to SSH: {adb_msg}")

        ssh_client = None
        sftp = None
        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='', timeout=15)

            def run(command):
                stdin, stdout, stderr = ssh_client.exec_command(command, timeout=30)
                rc = stdout.channel.recv_exit_status()
                output = (stdout.read().decode(errors="ignore") + stderr.read().decode(errors="ignore")).strip()
                return rc == 0, output

            run("mount -o remount,rw /oem 2>/dev/null || true")
            ok, output = run(f"mkdir -p {shlex.quote(remote_dir)}")
            if not ok:
                return False, f"创建远端目录失败: {output}"

            run("killall multi_media 2>/dev/null || true")
            time.sleep(1)
            still_running, process_info = run("ps aux | grep multi_media | grep -v grep")
            if still_running and process_info.strip():
                run("kill -9 $(ps aux | grep multi_media | grep -v grep | awk '{print $2}') 2>/dev/null || true")
                time.sleep(1)

            sftp = ssh_client.open_sftp()
            sftp.put(local_file, remote_full_path)
            uploaded_size = sftp.stat(remote_full_path).st_size
            local_size = os.path.getsize(local_file)
            if uploaded_size != local_size:
                return False, f"上传校验失败: 本地={local_size}, 远端={uploaded_size}"

            chmod_cmd = f"chmod 755 {shlex.quote(remote_full_path)} && sync"
            ok, output = run(chmod_cmd)
            if not ok:
                return False, f"chmod失败: {output}"

            sftp.close()
            sftp = None
            ssh_client.close()
            ssh_client = None

            restart_success, restart_msg = self.restart_media_process(device_ip)
            if not restart_success:
                return False, f"{label}已替换到 {remote_full_path}，但 multi_media 重启失败: {restart_msg}"

            return True, f"{label}已替换到 {remote_full_path}，chmod 755 已完成，multi_media 已重启"
        except Exception as e:
            log_manager.error(f"[RUNTIME] 替换{component_type}失败: {str(e)}", exc_info=True)
            return False, f"替换运行时组件失败: {str(e)}"
        finally:
            try:
                if sftp:
                    sftp.close()
                if ssh_client:
                    ssh_client.close()
            except Exception:
                pass
    
    def pull_config(self, config_filename, device_ip, local_path=None):
        """从设备下载配置文件
        
        Args:
            config_filename: 配置文件名（如 model_config.json）
            device_ip: 设备IP地址
            local_path: 本地保存路径，默认为当前目录
            
        Returns:
            (success, message_or_filepath): 成功返回(True, 文件路径)，失败返回(False, 错误信息)
        """
        if local_path is None:
            local_path = os.path.basename(config_filename)
        
        try:
            remote_path = f"/oem/usr/models/{config_filename}"

            adb_success, adb_result = self._pull_via_adb(remote_path, local_path)
            if adb_success:
                return True, local_path
            log_manager.warning(f"[ADB] config pull unavailable, fallback to SSH: {adb_result}")
            
            # 使用SSHClient下载
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='', timeout=10)
            
            sftp = ssh_client.open_sftp()
            sftp.get(remote_path, local_path)
            
            sftp.close()
            ssh_client.close()
            
            if os.path.exists(local_path):
                file_size = os.path.getsize(local_path)
                return True, local_path
            else:
                return False, "文件下载失败"
        except FileNotFoundError:
            return False, f"设备上不存在配置文件: {config_filename}"
        except Exception as e:
            return False, f"配置下载失败: {str(e)}"
            
    def push_video(self, video_file, device_ip, progress_callback=None, cancel_callback=None):
        """推送视频文件到设备/userdata目录
        
        Args:
            video_file: 本地视频文件路径
            device_ip: 设备IP地址
            progress_callback: 进度回调函数 callback(transferred, total)
        """
        try:
            remote_path = "/userdata/"
            remote_full_path = os.path.join(remote_path, os.path.basename(video_file))
            file_size = os.path.getsize(video_file)
            
            log_manager.info(f"[VIDEO] 开始上传视频: {os.path.basename(video_file)}")
            log_manager.info(f"[VIDEO] 文件大小: {file_size / 1024 / 1024:.2f} MB")

            adb_success, adb_msg = self._push_video_via_adb(
                video_file,
                remote_full_path,
                file_size,
                progress_callback,
                cancel_callback=cancel_callback,
            )
            if adb_success:
                return True, adb_msg
            if cancel_callback and cancel_callback():
                return False, "上传已取消"
            log_manager.warning(f"[VIDEO] ADB上传不可用，回退SSH: {adb_msg}")
            
            # 创建SSH客户端并设置超时
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='', timeout=15)
            
            sftp = ssh_client.open_sftp()
            
            # 定义进度回调
            def _progress_callback(transferred, total):
                if cancel_callback and cancel_callback():
                    raise InterruptedError("上传已取消")
                if progress_callback:
                    progress_callback(transferred, total)
                # 每10%记录一次日志
                percent = (transferred / total * 100) if total > 0 else 0
                if int(percent) % 10 == 0 and int(percent) > 0:
                    log_manager.info(f"[VIDEO] 上传进度: {percent:.1f}% ({transferred / 1024 / 1024:.2f} MB / {total / 1024 / 1024:.2f} MB)")
            
            # 上传文件（带进度）
            sftp.put(video_file, remote_full_path, callback=_progress_callback)
            
            # 验证文件是否成功上传
            file_stat = sftp.stat(remote_full_path)
            uploaded_size = file_stat.st_size
            
            sftp.close()
            ssh_client.close()
            
            if uploaded_size == file_size:
                log_manager.info(f"[VIDEO] 视频上传成功: {remote_full_path}")
                return True, f"视频已上传到 {remote_full_path} ({file_size / 1024 / 1024:.2f} MB)"
            else:
                log_manager.error(f"[VIDEO] 文件大小不匹配: 本地={file_size}, 远程={uploaded_size}")
                return False, f"上传验证失败：文件大小不匹配"
                
        except InterruptedError:
            try:
                if 'sftp' in locals() and sftp:
                    sftp.remove(remote_full_path)
            except Exception:
                pass
            try:
                if 'sftp' in locals() and sftp:
                    sftp.close()
                if 'ssh_client' in locals() and ssh_client:
                    ssh_client.close()
            except Exception:
                pass
            return False, "上传已取消"
        except paramiko.SSHException as e:
            log_manager.error(f"[VIDEO] SSH连接失败: {str(e)}")
            return False, f"SSH连接失败: {str(e)}"
        except IOError as e:
            log_manager.error(f"[VIDEO] 文件传输失败: {str(e)}")
            return False, f"文件传输失败: {str(e)}"
        except Exception as e:
            log_manager.error(f"[VIDEO] 视频上传异常: {str(e)}", exc_info=True)
            return False, f"视频上传失败: {str(e)}"

    def _push_video_via_adb(
        self,
        video_file,
        remote_full_path,
        file_size,
        progress_callback=None,
        cancel_callback=None,
    ):
        """Push video through USB ADB with live progress and cancellation."""
        device_id, msg = self.get_adb_device_id()
        if not device_id:
            return False, msg

        process = None
        try:
            if progress_callback:
                progress_callback(0, file_size)

            # Clear stale same-name file so remote-size polling starts at zero.
            self.run_adb_shell_command(
                f"rm -f {shlex.quote(remote_full_path)}",
                device_id=device_id,
                timeout=10,
            )

            process = subprocess.Popen(
                ["adb", "-s", device_id, "push", video_file, remote_full_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            last_emit = 0.0
            last_transferred = -1
            while process.poll() is None:
                if cancel_callback and cancel_callback():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    self.run_adb_shell_command(
                        f"rm -f {shlex.quote(remote_full_path)}",
                        device_id=device_id,
                        timeout=10,
                    )
                    if progress_callback:
                        progress_callback(max(last_transferred, 0), file_size)
                    return False, "上传已取消"

                now = time.monotonic()
                if now - last_emit >= 0.25:
                    uploaded_size, _ = self._get_adb_file_size(device_id, remote_full_path)
                    if uploaded_size is not None:
                        uploaded_size = max(0, min(uploaded_size, file_size))
                        if uploaded_size != last_transferred:
                            last_transferred = uploaded_size
                            if progress_callback:
                                progress_callback(uploaded_size, file_size)
                    last_emit = now
                time.sleep(0.05)

            process.wait(timeout=5)
            if process.returncode != 0:
                self.run_adb_shell_command(
                    f"rm -f {shlex.quote(remote_full_path)}",
                    device_id=device_id,
                    timeout=10,
                )
                return False, f"adb push返回码 {process.returncode}"

            uploaded_size, stat_output = self._get_adb_file_size(device_id, remote_full_path)
            if uploaded_size is not None and uploaded_size != file_size:
                return False, f"ADB上传验证失败: 本地={file_size}, 远程={uploaded_size}"
            if uploaded_size is None:
                log_manager.warning(f"[VIDEO] ADB file size check skipped: {stat_output}")

            if progress_callback:
                progress_callback(file_size, file_size)
            log_manager.info(f"[VIDEO] ADB upload success: {remote_full_path}")
            return True, f"视频已通过ADB上传到 {remote_full_path} ({file_size / 1024 / 1024:.2f} MB)"
        except Exception as e:
            if cancel_callback and cancel_callback():
                try:
                    if process and process.poll() is None:
                        process.kill()
                except Exception:
                    pass
                self.run_adb_shell_command(
                    f"rm -f {shlex.quote(remote_full_path)}",
                    device_id=device_id,
                    timeout=10,
                )
                return False, "上传已取消"
            return False, f"ADB上传失败: {str(e)}"

    def list_device_videos(self, device_ip):
        """列出设备 /userdata 目录下的视频文件。"""
        try:
            device_id, adb_msg = self.get_adb_device_id()
            if device_id:
                command = (
                    "find /userdata -maxdepth 1 -type f 2>/dev/null | "
                    "grep -Ei '\\.(h264|264|h265|265|hevc|mp4|ts|mkv|avi|mov)$' | "
                    "while read f; do ls -lh \"$f\"; done"
                )
                adb_success, adb_output = self.run_adb_shell_command(command, device_id=device_id, timeout=20)
                if adb_success:
                    videos = []
                    for line in adb_output.strip().splitlines():
                        parts = line.split()
                        if len(parts) < 9:
                            continue
                        remote_path = parts[-1]
                        videos.append(
                            {
                                "name": os.path.basename(remote_path),
                                "path": remote_path,
                                "size": parts[4],
                                "mtime": " ".join(parts[5:8]),
                                "raw": line,
                            }
                        )
                    return True, f"找到 {len(videos)} 个视频文件", videos
                log_manager.warning(f"[ADB] list videos failed, fallback to SSH: {adb_output}")
            else:
                log_manager.info(f"[ADB] list videos skipped: {adb_msg}")

            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)

            command = (
                "find /userdata -maxdepth 1 -type f 2>/dev/null | "
                "grep -Ei '\\.(h264|264|h265|265|hevc|mp4|ts|mkv|avi|mov)$' | "
                "while read f; do ls -lh \"$f\"; done"
            )
            success, output = self.execute_ssh_command(command)
            if not success:
                return False, f"获取视频列表失败: {output}", []

            videos = []
            for line in output.strip().splitlines():
                parts = line.split()
                if len(parts) < 9:
                    continue
                remote_path = parts[-1]
                videos.append(
                    {
                        "name": os.path.basename(remote_path),
                        "path": remote_path,
                        "size": parts[4],
                        "mtime": " ".join(parts[5:8]),
                        "raw": line,
                    }
                )
            return True, f"找到 {len(videos)} 个视频文件", videos
        except Exception as e:
            log_manager.error(f"[VIDEO] 获取设备视频列表失败: {str(e)}", exc_info=True)
            return False, f"获取设备视频列表失败: {str(e)}", []

    def list_device_tracking_jsons(self, device_ip):
        """列出设备 /userdata 目录下的追踪 JSON 文件，按修改时间倒序。"""
        try:
            device_id, adb_msg = self.get_adb_device_id()
            if device_id:
                adb_success, adb_output = self.run_adb_shell_command(
                    "ls -lt /userdata/*.json 2>/dev/null || true",
                    device_id=device_id,
                    timeout=20,
                )
                if adb_success:
                    json_files = []
                    for line in adb_output.strip().splitlines():
                        parts = line.split()
                        if len(parts) < 9:
                            continue
                        remote_path = parts[-1]
                        json_files.append(
                            {
                                "name": os.path.basename(remote_path),
                                "path": remote_path,
                                "size": parts[4],
                                "mtime": " ".join(parts[5:8]),
                                "raw": line,
                            }
                        )
                    return True, f"找到 {len(json_files)} 个追踪JSON文件", json_files
                log_manager.warning(f"[ADB] list tracking json failed, fallback to SSH: {adb_output}")
            else:
                log_manager.info(f"[ADB] list tracking json skipped: {adb_msg}")

            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)

            command = "ls -lt /userdata/*.json 2>/dev/null || true"
            success, output = self.execute_ssh_command(command)
            if not success:
                return False, f"获取追踪JSON列表失败: {output}", []

            json_files = []
            for line in output.strip().splitlines():
                parts = line.split()
                if len(parts) < 9:
                    continue
                remote_path = parts[-1]
                json_files.append(
                    {
                        "name": os.path.basename(remote_path),
                        "path": remote_path,
                        "size": parts[4],
                        "mtime": " ".join(parts[5:8]),
                        "raw": line,
                    }
                )
            return True, f"找到 {len(json_files)} 个追踪JSON文件", json_files
        except Exception as e:
            log_manager.error(f"[VIDEO] 获取追踪JSON列表失败: {str(e)}", exc_info=True)
            return False, f"获取追踪JSON列表失败: {str(e)}", []

    def download_remote_file(self, device_ip, remote_path, local_path, progress_callback=None):
        """通过 SFTP 下载设备文件。"""
        ssh_client = None
        sftp = None
        adb_success, adb_result = self._pull_via_adb(remote_path, local_path, progress_callback)
        if adb_success:
            return True, local_path
        log_manager.warning(f"[ADB] file pull unavailable, fallback to SSH: {adb_result}")
        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='', timeout=15)
            sftp = ssh_client.open_sftp()
            total = sftp.stat(remote_path).st_size
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            def _progress(transferred, total_size):
                if progress_callback:
                    progress_callback(transferred, total_size or total)

            sftp.get(remote_path, local_path, callback=_progress)
            return True, local_path
        except Exception as e:
            return False, f"下载失败: {str(e)}"
        finally:
            try:
                if sftp:
                    sftp.close()
                if ssh_client:
                    ssh_client.close()
            except Exception:
                pass

    def _get_config_mode(self, config, mode_id):
        for mode in config.get("modes", []) or []:
            if mode_id is None or str(mode.get("id")) == str(mode_id):
                return mode
        return None

    def _update_config_video_source(self, config, video_src_type, mode_id=None, model_index=None):
        changed = 0
        for mode in config.get("modes", []) or []:
            if mode_id is not None and str(mode.get("id")) != str(mode_id):
                continue
            models = mode.get("models", []) or []
            if model_index is not None:
                if model_index < 0 or model_index >= len(models):
                    continue
                targets = [models[model_index]]
            else:
                targets = models
            for model in targets:
                if isinstance(model, dict):
                    model["videoSrcType"] = video_src_type
                    changed += 1
        return changed

    def _update_tracking_mode_fields(self, config, mode_id, mode_updates=None):
        if not mode_updates:
            return 0

        mode = self._get_config_mode(config, mode_id)
        if not mode:
            return 0

        changed = 0
        for field, value in (mode_updates.get("mode_fields") or {}).items():
            mode[field] = value
            changed += 1

        model_fields = mode_updates.get("model_fields") or {}
        if model_fields:
            model_index = int(mode_updates.get("model_index", 0) or 0)
            models = mode.get("models", []) or []
            if model_index < 0 or model_index >= len(models):
                return changed
            model = models[model_index]
            if isinstance(model, dict):
                for field, value in model_fields.items():
                    model[field] = value
                    changed += 1

        return changed

    def apply_video_source_config(
        self,
        device_ip,
        source_type,
        remote_video_path=None,
        mode_id=None,
        video_src_type=None,
        mode_updates=None,
    ):
        """修改 model_config.json 中的指定追踪模式配置并重启 multi_media。"""
        config_filename = "model_config.json"
        temp_dir = "_tmp_video_source"
        temp_file = os.path.join(temp_dir, config_filename)
        try:
            if source_type not in ("camera", "file"):
                return False, f"未知视频源类型: {source_type}"
            video_src_type = video_src_type or ("FILE_H264" if source_type == "file" else "ANA_CAMERA")
            if video_src_type not in ("ANA_CAMERA", "CAP_CAMERA", "FILE_H264"):
                return False, f"未知 videoSrcType: {video_src_type}"
            if video_src_type == "FILE_H264" and not remote_video_path:
                return False, "请选择设备 /userdata 下的视频文件"

            os.makedirs(temp_dir, exist_ok=True)
            success, result = self.pull_config(config_filename, device_ip, temp_file)
            if not success:
                return False, result

            with open(temp_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            changed = self._update_tracking_mode_fields(config, mode_id, mode_updates=mode_updates)
            model_index = None
            if mode_updates and "model_index" in mode_updates:
                model_index = int(mode_updates.get("model_index", 0) or 0)
            changed += self._update_config_video_source(
                config,
                video_src_type,
                mode_id=mode_id,
                model_index=model_index,
            )
            if changed == 0:
                if mode_id is not None:
                    return False, f"model_config.json 中未找到模式 {mode_id} 下可修改的配置"
                return False, "model_config.json 中未找到可修改的配置"

            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            success, msg = self.push_config(temp_file, device_ip)
            if not success:
                return False, msg

            extra_env = None
            if video_src_type == "FILE_H264":
                extra_env = {
                    "DECODE_MODE": "MPP",
                    "H264_VIDEO_PATH": remote_video_path,
                }

            restart_success, restart_msg = self.restart_media_process(device_ip, extra_env=extra_env)
            if not restart_success:
                return False, f"配置已更新，但 multi_media 重启失败: {restart_msg}"

            mode_text = f"模式 {mode_id} " if mode_id is not None else ""
            if video_src_type == "FILE_H264":
                return True, f"已更新{mode_text}配置，切换到本地视频: {remote_video_path}，并使用 MPP 硬解启动"
            return True, f"已更新{mode_text}配置，切换到 {video_src_type} 并重启 multi_media"
        except Exception as e:
            log_manager.error(f"[VIDEO] 应用视频源配置失败: {str(e)}", exc_info=True)
            return False, f"应用视频源配置失败: {str(e)}"
        finally:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                if os.path.isdir(temp_dir):
                    os.rmdir(temp_dir)
            except OSError:
                pass
            
    def list_models(self, device_ip, connection_type='SSH'):
        """列出设备上的模型文件"""
        try:
            models = self._list_models_adb(device_ip)
            if models:
                return models
            if connection_type != 'SSH':
                return models
            return self._list_models_ssh(device_ip)
        except Exception as e:
            print(f"获取模型列表失败: {e}")
            return []
            
    def _list_models_ssh(self, device_ip):
        """通过SSH列出模型"""
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
                
            command = "ls -lh /oem/usr/models/*.rknn"
            success, output = self.execute_ssh_command(command)
            
            if success:
                models = []
                for line in output.strip().split('\n'):
                    if line and '.rknn' in line:
                        parts = line.split()
                        if len(parts) >= 9:
                            models.append({
                                'name': parts[-1].split('/')[-1],
                                'size': parts[4],
                                'mtime': ' '.join(parts[5:8])
                            })
                return models
            else:
                return []
                
        except Exception as e:
            print(f"SSH列出模型失败: {e}")
            return []
            
    def _list_models_adb(self, device_ip):
        """通过ADB列出模型"""
        try:
            device_id, msg = self.get_adb_device_id()
            if not device_id:
                log_manager.info(f"[ADB] list models skipped: {msg}")
                return []

            result = _run_subprocess_text(
                ['adb', '-s', device_id, 'shell', 'ls', '-lh', '/oem/usr/models/*.rknn'],
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                models = []
                for line in result.stdout.strip().split('\n'):
                    if line and '.rknn' in line:
                        # ADB输出格式可能不同，需要适配
                        parts = line.split()
                        if len(parts) >= 2:
                            # 取最后一个部分作为文件名
                            filename = parts[-1]
                            if '/' in filename:
                                filename = filename.split('/')[-1]
                            models.append({
                                'name': filename,
                                'size': parts[3] if len(parts) > 3 else 'N/A',
                                'mtime': ' '.join(parts[5:8]) if len(parts) >= 8 else 'N/A'
                            })
                return models
            else:
                return []
                
        except Exception as e:
            print(f"ADB列出模型失败: {e}")
            return []

    def delete_model(self, model_name, device_ip):
        """从设备删除模型文件"""
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
            
            remote_path = f"/oem/usr/models/{model_name}"
            
            # 执行删除命令
            command = f"rm -f {remote_path}"
            success, msg = self.execute_ssh_command(command)
            
            if success:
                return True, f"模型 {model_name} 已删除"
            else:
                return False, f"删除失败: {msg}"
                
        except Exception as e:
            return False, f"删除模型失败: {str(e)}"

    def check_disk_space(self, device_ip, path='/oem'):
        """检查设备磁盘空间"""
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
            
            # 执行df命令检查磁盘空间
            command = f"df -h {path}"
            success, output = self.execute_ssh_command(command)
            
            if success and output.strip():
                log_manager.info(f"[DISK] 磁盘空间信息:\n{output}")
                
                # 解析输出，提取可用空间信息
                lines = output.strip().split('\n')
                if len(lines) >= 2:
                    # 第二行是实际数据
                    parts = lines[1].split()
                    if len(parts) >= 5:
                        filesystem = parts[0]
                        size = parts[1]
                        used = parts[2]
                        available = parts[3]
                        use_percent = parts[4]
                        
                        return {
                            'success': True,
                            'filesystem': filesystem,
                            'size': size,
                            'used': used,
                            'use_percent': use_percent,
                            'available': available,
                            'raw_output': output
                        }
                
                return {'success': True, 'raw_output': output}
            else:
                return {'success': False, 'error': '无法获取磁盘空间信息'}
                
        except Exception as e:
            log_manager.error(f"[DISK] 检查磁盘空间失败: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def get_model_sizes(self, device_ip):
        """获取所有模型文件的大小信息"""
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
            
            # 列出所有模型文件及其大小
            command = "ls -lh /oem/usr/models/*.rknn 2>/dev/null || echo 'No models found'"
            success, output = self.execute_ssh_command(command)
            
            if success and output.strip() and 'No models found' not in output:
                models_info = []
                for line in output.strip().split('\n'):
                    if line and '.rknn' in line:
                        parts = line.split()
                        if len(parts) >= 9:
                            size = parts[4]
                            filename = parts[-1].split('/')[-1]
                            models_info.append({
                                'name': filename,
                                'size': size,
                                'full_line': line
                            })
                
                return {'success': True, 'models': models_info}
            else:
                return {'success': True, 'models': [], 'message': '没有找到模型文件'}
                
        except Exception as e:
            log_manager.error(f"[DISK] 获取模型大小失败: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def restart_media_process(self, device_ip, extra_env=None):
        """重启multi_media进程"""
        device_id, adb_msg = self.get_adb_device_id()
        if device_id:
            adb_success, adb_restart_msg = self._restart_media_process_via_adb(
                device_id,
                extra_env=extra_env,
            )
            if adb_success:
                self.current_adb_device_id = device_id
                self.connection_mode = "adb"
                return True, adb_restart_msg
            log_manager.error(f"[ADB] restart multi_media failed: {adb_restart_msg}")
            return False, adb_restart_msg
        else:
            log_manager.info(f"[ADB] restart multi_media skipped: {adb_msg}")

        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
            
            log_manager.info(f"[进程] 正在重启设备 {device_ip} 上的multi_media进程...")
                
            # 先杀掉进程
            kill_success, kill_msg = self.execute_ssh_command("killall multi_media")
            if not kill_success:
                log_manager.warning(f"[进程] 杀死进程失败或进程不存在: {kill_msg}")
            
            # 等待进程完全停止
            import time
            time.sleep(2)
            
            # 验证进程已被杀死
            verify_kill, verify_msg = self.execute_ssh_command("ps aux | grep multi_media | grep -v grep")
            if verify_kill and verify_msg.strip():
                log_manager.warning(f"[进程] 进程仍然存在，尝试强制杀死: {verify_msg}")
                self.execute_ssh_command("kill -9 $(ps aux | grep multi_media | grep -v grep | awk '{print $2}')")
                time.sleep(1)

            # 生成带时间戳的日志文件名
            import datetime
            timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            log_dir = "/userdata/logs"
            log_file = f"{log_dir}/multi_media-{timestamp}-redir.log"
            
            # 确保日志目录存在
            self.execute_ssh_command(f"mkdir -p {log_dir}")
            
            env_parts = [
                "export TARGET_DIR=/oem",
                "export LD_LIBRARY_PATH=/oem/usr/lib:/lib:${LD_LIBRARY_PATH:-}",
                "export PATH=/oem/usr/bin:/bin:${PATH:-}",
            ]
            for key, value in (extra_env or {}).items():
                env_parts.append(f"export {key}={shlex.quote(str(value))}")

            start_command = (
                "; ".join(env_parts) + "; "
                "rm -f /tmp/multi_media.pid; "
                "cd /oem/usr/bin || exit 1; "
                "start-stop-daemon -S -b -m -p /tmp/multi_media.pid "
                f"-x /oem/usr/bin/multi_media > {shlex.quote(log_file)} 2>&1"
            )
            log_manager.info(f"[进程] 执行启动命令: {start_command}")
            log_manager.info(f"[进程] 日志文件: {log_file}")
            
            start_success, start_msg = self.execute_ssh_command(start_command)
            
            if start_success:
                # 等待进程启动
                time.sleep(2)
                
                # 验证进程是否成功启动
                verify_start, verify_msg = self.execute_ssh_command("ps aux | grep multi_media | grep -v grep")
                if verify_start and verify_msg.strip():
                    log_manager.info(f"[进程] multi_media进程重启成功！进程信息: {verify_msg.strip()}")
                    return True, "multi_media进程已重启"
                else:
                    log_manager.error(f"[进程] 进程启动后未找到，可能启动失败")
                    return False, "进程启动失败：进程未运行"
            else:
                log_manager.error(f"[进程] 执行启动命令失败: {start_msg}")
                return False, f"重启失败: {start_msg}"
                
        except Exception as e:
            log_manager.error(f"[进程] 重启进程异常: {str(e)}")
            return False, f"重启进程失败: {str(e)}"
            
    def kill_media_process(self, device_ip):
        """停止multi_media进程"""
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
                
            command = "killall multi_media"
            success, msg = self.execute_ssh_command(command)
            
            if success or "no process found" in msg.lower():
                return True, "multi_media进程已停止"
            else:
                return False, f"停止失败: {msg}"
                
        except Exception as e:
            return False, f"停止进程失败: {str(e)}"
            
    def get_device_info(self, device_ip):
        """获取设备信息"""
        info = {}
        
        try:
            if not self._usb_adb_available() and not self.ssh_client:
                self.connect_ssh(device_ip)
                
            # 获取CPU信息
            success, output = self.execute_ssh_command("top -bn1 | grep 'Cpu(s)'")
            if success:
                info['cpu'] = output.strip()
                
            # 获取内存信息
            success, output = self.execute_ssh_command("free -m")
            if success:
                info['memory'] = output.strip()
                
            # 获取NPU信息
            success, output = self.execute_ssh_command("cat /sys/kernel/debug/rknpu/load")
            if success:
                info['npu'] = output.strip()
                
        except Exception as e:
            info['error'] = str(e)
            
        return info
