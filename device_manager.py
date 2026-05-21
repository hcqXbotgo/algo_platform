# -*- coding: utf-8 -*-
"""
设备管理模块
功能：SSH/ADB连接、文件推送、进程管理
"""

import paramiko
import subprocess
import os
from datetime import datetime
from log_manager import log_manager


class DeviceManager:
    """设备管理器，处理SSH和ADB连接"""
    
    def __init__(self):
        self.ssh_client = None
        self.current_device_ip = None  # 保存当前连接的设备IP
        
    def connect_ssh(self, hostname, username='root', password='', port=22):
        """建立SSH连接"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(hostname, port=port, username=username, password=password, timeout=10)
            self.current_device_ip = hostname  # 保存设备IP
            return True, "SSH连接成功"
        except Exception as e:
            return False, f"SSH连接失败: {str(e)}"
            
    def execute_ssh_command(self, command):
        """执行SSH命令（自动重连）"""
        # 如果没有SSH连接，尝试自动重连到上次连接的设备
        if not self.ssh_client and self.current_device_ip:
            log_manager.info(f"[DEVICE] SSH连接已关闭，正在自动重连到 {self.current_device_ip}...")
            success, msg = self.connect_ssh(self.current_device_ip)
            if not success:
                log_manager.error(f"[DEVICE] 自动重连失败: {msg}")
                return False, f"未建立SSH连接且自动重连失败: {msg}"
            log_manager.info(f"[DEVICE] 自动重连成功")
        
        if not self.ssh_client:
            return False, "未建立SSH连接"
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
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
            
            if connection_type == 'SSH':
                # 使用SCP推送
                success, msg = self._push_via_scp(model_file, device_ip, remote_path)
            else:  # ADB
                success, msg = self._push_via_adb(model_file, device_ip, remote_path)
                
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
            # 首先连接到设备
            subprocess.run(['adb', 'connect', device_ip], check=True, capture_output=True)
            
            remote_full_path = f"{remote_path}{os.path.basename(local_file)}"
            result = subprocess.run(
                ['adb', 'push', local_file, remote_full_path],
                check=True,
                capture_output=True,
                text=True
            )
            
            subprocess.run(['adb', 'disconnect', device_ip], capture_output=True)
            
            return True, f"文件已通过ADB上传: {remote_full_path}"
        except Exception as e:
            return False, f"ADB上传失败: {str(e)}"
            
    def push_config(self, config_file, device_ip):
        """推送配置文件到设备"""
        try:
            remote_path = "/oem/usr/models/"
            remote_full_path = os.path.join(remote_path, os.path.basename(config_file))
            
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
            
    def push_video(self, video_file, device_ip, progress_callback=None):
        """推送视频文件到设备/userdata目录
        
        Args:
            video_file: 本地视频文件路径
            device_ip: 设备IP地址
            progress_callback: 进度回调函数 callback(transferred, total)
        """
        try:
            remote_path = "/userdata/"
            remote_full_path = os.path.join(remote_path, os.path.basename(video_file))
            
            log_manager.info(f"[VIDEO] 开始上传视频: {os.path.basename(video_file)}")
            
            # 创建SSH客户端并设置超时
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(device_ip, port=22, username='root', password='', timeout=15)
            
            sftp = ssh_client.open_sftp()
            
            # 获取文件大小
            file_size = os.path.getsize(video_file)
            log_manager.info(f"[VIDEO] 文件大小: {file_size / 1024 / 1024:.2f} MB")
            
            # 定义进度回调
            def _progress_callback(transferred, total):
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
                
        except paramiko.SSHException as e:
            log_manager.error(f"[VIDEO] SSH连接失败: {str(e)}")
            return False, f"SSH连接失败: {str(e)}"
        except IOError as e:
            log_manager.error(f"[VIDEO] 文件传输失败: {str(e)}")
            return False, f"文件传输失败: {str(e)}"
        except Exception as e:
            log_manager.error(f"[VIDEO] 视频上传异常: {str(e)}", exc_info=True)
            return False, f"视频上传失败: {str(e)}"
            
    def list_models(self, device_ip, connection_type='SSH'):
        """列出设备上的模型文件"""
        try:
            if connection_type == 'SSH':
                return self._list_models_ssh(device_ip)
            else:  # ADB
                return self._list_models_adb(device_ip)
        except Exception as e:
            print(f"获取模型列表失败: {e}")
            return []
            
    def _list_models_ssh(self, device_ip):
        """通过SSH列出模型"""
        try:
            if not self.ssh_client:
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
            import subprocess
            
            # 连接到设备
            result = subprocess.run(
                ['adb', 'connect', device_ip],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # 列出模型文件
            result = subprocess.run(
                ['adb', '-s', device_ip, 'shell', 'ls', '-lh', '/oem/usr/models/*.rknn'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # 断开连接
            subprocess.run(['adb', 'disconnect', device_ip], capture_output=True, timeout=5)
            
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
            if not self.ssh_client:
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
            if not self.ssh_client:
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
            if not self.ssh_client:
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

    def update_video_source(self, device_ip, ini_path, video_src):
        """更新视频源配置"""
        try:
            if not self.ssh_client:
                self.connect_ssh(device_ip)
                
            # 读取当前配置
            command = f"cat {ini_path}"
            success, content = self.execute_ssh_command(command)
            
            if not success:
                return False, f"读取配置失败: {content}"
                
            # 修改配置
            lines = content.split('\n')
            new_lines = []
            in_video_section = False
            
            for line in lines:
                if line.strip() == '[video_src]':
                    in_video_section = True
                    new_lines.append(line)
                elif in_video_section and line.startswith('source'):
                    new_lines.append(f"source = {video_src}")
                    in_video_section = False
                else:
                    new_lines.append(line)
                    
            # 如果没有找到video_src部分，添加它
            if not any('[video_src]' in line for line in lines):
                new_lines.append('\n[video_src]')
                new_lines.append(f'source = {video_src}')
                
            new_content = '\n'.join(new_lines)
            
            # 写回文件
            command = f"echo '{new_content}' > {ini_path}"
            success, msg = self.execute_ssh_command(command)
            
            if success:
                return True, "视频源配置已更新"
            else:
                return False, f"写入配置失败: {msg}"
                
        except Exception as e:
            return False, f"更新配置失败: {str(e)}"
            
    def restart_media_process(self, device_ip):
        """重启multi_media进程"""
        try:
            if not self.ssh_client:
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
            
            start_command = (
                "export LD_LIBRARY_PATH=/oem/usr/lib:/lib && "
                f"exec setsid /oem/usr/bin/multi_media "
                f"> {log_file} 2>&1 < /dev/null &"
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
            if not self.ssh_client:
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
            if not self.ssh_client:
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
