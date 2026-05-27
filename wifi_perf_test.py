# -*- coding: utf-8 -*-
"""
WiFi性能测试模块
功能：使用iperf3进行UDP带宽测试，测量抖动、丢包率、延迟、RSSI和协商速率
"""

import subprocess
import re
import json
import time
import csv
import os
from datetime import datetime
from log_manager import LogManager

log_manager = LogManager()


class WiFiPerfTester:
    """WiFi性能测试器"""
    
    def __init__(self, device_ip=None):
        self.device_ip = device_ip
        self.iperf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iperf3.exe')
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
        
    def get_wifi_info(self):
        """获取WiFi信息（RSSI和协商速率）
        
        Returns:
            dict: 包含rssi和link_speed的信息
        """
        if not self.device_ip:
            return {'rssi': 0, 'link_speed': 0}
            
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.device_ip, port=22, username='root', password='', timeout=10)
            
            # 获取RSSI
            stdin, stdout, stderr = ssh.exec_command('iw dev wlan0 link | grep signal', timeout=5)
            rssi_output = stdout.read().decode('utf-8').strip()
            rssi = 0
            if rssi_output:
                match = re.search(r'signal:\s*(-?\d+)\s*dBm', rssi_output)
                if match:
                    rssi = int(match.group(1))
            
            # 获取协商速率 (tx bitrate)
            stdin, stdout, stderr = ssh.exec_command('iw dev wlan0 link | grep tx bitrate', timeout=5)
            speed_output = stdout.read().decode('utf-8').strip()
            link_speed = 0
            if speed_output:
                match = re.search(r'tx bitrate:\s*([\d.]+)\s*Mbit/s', speed_output)
                if match:
                    link_speed = float(match.group(1))
            
            ssh.close()
            
            return {
                'rssi': rssi,
                'link_speed': link_speed
            }
            
        except Exception as e:
            log_manager.error(f"获取WiFi信息失败: {str(e)}")
            return {'rssi': 0, 'link_speed': 0}
    
    def start_iperf_server(self):
        """在设备上启动iperf3服务器
        
        Returns:
            tuple: (success, message)
        """
        if not self.device_ip:
            return False, "未设置设备IP地址"
            
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.device_ip, port=22, username='root', password='', timeout=10)
            
            # 先停止可能存在的iperf3进程
            ssh.exec_command('killall iperf3 2>/dev/null', timeout=5)
            time.sleep(1)
            
            # 启动iperf3服务器（后台运行）
            stdin, stdout, stderr = ssh.exec_command('iperf3 -s -D', timeout=5)
            exit_code = stdout.channel.recv_exit_status()
            
            time.sleep(2)  # 等待服务器启动
            
            # 检查是否成功启动
            stdin, stdout, stderr = ssh.exec_command('ps aux | grep iperf3 | grep -v grep', timeout=5)
            output = stdout.read().decode('utf-8').strip()
            
            ssh.close()
            
            if 'iperf3' in output:
                log_manager.info("设备上iperf3服务器已启动")
                return True, "iperf3服务器启动成功"
            else:
                return False, "iperf3服务器启动失败"
                
        except Exception as e:
            error_msg = f"启动iperf3服务器失败: {str(e)}"
            log_manager.error(error_msg)
            return False, error_msg
    
    def stop_iperf_server(self):
        """停止设备上的iperf3服务器"""
        if not self.device_ip:
            return
            
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.device_ip, port=22, username='root', password='', timeout=10)
            
            ssh.exec_command('killall iperf3', timeout=5)
            ssh.close()
            
            log_manager.info("设备上iperf3服务器已停止")
            
        except Exception as e:
            log_manager.error(f"停止iperf3服务器失败: {str(e)}")
    
    def run_udp_test(self, bandwidth_mbps=10, duration=10, callback=None):
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
        
        try:
            # 构建iperf3命令（移除旧版本不支持的参数）
            cmd = [
                self.iperf_path,
                '-c', self.device_ip,
                '-u',  # UDP模式
                '-b', f'{bandwidth_mbps}M',  # 目标带宽
                '-t', str(duration),  # 测试时长
                '-i', '1',  # 每秒报告一次
                '-J'  # JSON格式输出
            ]
            
            if callback:
                callback(20, "正在执行iperf3测试...")
            
            log_manager.info(f"执行命令: {' '.join(cmd)}")
            
            # 执行iperf3测试
            start_time = time.time()
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self._current_process = process
            
            stdout, stderr = process.communicate(timeout=duration + 30)
            elapsed_time = time.time() - start_time

            if self._cancel_requested:
                return None, "测试已取消"
            
            if callback:
                callback(80, "正在解析测试结果...")
            
            # 解析JSON结果
            try:
                result_json = json.loads(stdout.decode('utf-8'))
                
                # 提取关键指标
                end_summary = result_json.get('end', {})
                sum_sent = end_summary.get('sum_sent', {})
                sum_received = end_summary.get('sum_received', {})
                
                # 计算平均延迟（从intervals中获取）
                intervals = result_json.get('intervals', [])
                latencies = []
                for interval in intervals:
                    streams = interval.get('streams', [])
                    for stream in streams:
                        if 'udp' in stream:
                            udp_info = stream['udp']
                            if 'jitter_ms' in udp_info:
                                latencies.append(udp_info['jitter_ms'])
                
                avg_latency = sum(latencies) / len(latencies) if latencies else 0
                
                # 提取总体统计
                jitter = sum_received.get('jitter_ms', 0)
                packets_sent = sum_sent.get('packets', 0)
                packets_received = sum_received.get('packets', 0)
                lost_packets = packets_sent - packets_received
                loss_percent = (lost_packets / packets_sent * 100) if packets_sent > 0 else 0
                bits_per_second = sum_received.get('bits_per_second', 0)
                mbps_received = bits_per_second / 1e6
                
                # 获取WiFi信息
                wifi_info = self.get_wifi_info()
                
                test_result = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'bandwidth_target': bandwidth_mbps,
                    'duration': duration,
                    'throughput_mbps': round(mbps_received, 2),
                    'jitter_ms': round(jitter, 2),
                    'loss_percent': round(loss_percent, 2),
                    'avg_latency_ms': round(avg_latency, 2),
                    'rssi_dbm': wifi_info['rssi'],
                    'link_speed_mbps': wifi_info['link_speed'],
                    'packets_sent': packets_sent,
                    'packets_received': packets_received,
                    'elapsed_time': round(elapsed_time, 2)
                }
                
                self.test_results.append(test_result)
                
                if callback:
                    callback(100, "测试完成")
                
                log_manager.info(f"UDP测试完成: 吞吐量={mbps_received:.2f}Mbps, "
                               f"抖动={jitter:.2f}ms, 丢包={loss_percent:.2f}%")
                
                return test_result, "测试成功"
                
            except json.JSONDecodeError as e:
                error_msg = f"解析iperf3结果失败: {str(e)}"
                log_manager.error(error_msg)
                if stderr:
                    log_manager.error(f"stderr: {stderr.decode('utf-8')}")
                return None, error_msg
                
        except subprocess.TimeoutExpired:
            if self._current_process and self._current_process.poll() is None:
                self._current_process.kill()
            error_msg = "iperf3测试超时"
            log_manager.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"UDP测试失败: {str(e)}"
            log_manager.error(error_msg)
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
            
            result, msg = self.run_udp_test(bandwidth_mbps=bw, duration=duration)
            
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
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"wifi_perf_test_{timestamp}.csv"
        
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = [
                    '时间戳', '目标带宽(Mbps)', '测试时长(s)', 
                    '实际吞吐量(Mbps)', '抖动(ms)', '丢包率(%)',
                    '平均延迟(ms)', 'RSSI(dBm)', '协商速率(Mbps)',
                    '发送数据包', '接收数据包', '耗时(s)'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in self.test_results:
                    writer.writerow({
                        '时间戳': result['timestamp'],
                        '目标带宽(Mbps)': result['bandwidth_target'],
                        '测试时长(s)': result['duration'],
                        '实际吞吐量(Mbps)': result['throughput_mbps'],
                        '抖动(ms)': result['jitter_ms'],
                        '丢包率(%)': result['loss_percent'],
                        '平均延迟(ms)': result['avg_latency_ms'],
                        'RSSI(dBm)': result['rssi_dbm'],
                        '协商速率(Mbps)': result['link_speed_mbps'],
                        '发送数据包': result['packets_sent'],
                        '接收数据包': result['packets_received'],
                        '耗时(s)': result['elapsed_time']
                    })
            
            log_manager.info(f"测试结果已导出到: {filepath}")
            return filepath, "导出成功"
            
        except Exception as e:
            error_msg = f"导出CSV失败: {str(e)}"
            log_manager.error(error_msg)
            return None, error_msg
    
    def clear_results(self):
        """清空测试结果"""
        self.test_results.clear()
        log_manager.info("测试结果已清空")
