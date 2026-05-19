# -*- coding: utf-8 -*-
"""
MQTT控制模块
功能：发送追踪算法控制指令
"""

import paho.mqtt.client as mqtt
import json
from log_manager import LogManager

# 获取全局日志管理器实例
log_manager = LogManager()


class MQTTController:
    """MQTT控制器"""
    
    def __init__(self, device_ip=None):
        """初始化MQTT控制器
        
        Args:
            device_ip: 设备IP地址（可选，后续可动态设置）
        """
        self.device_ip = device_ip
        self.client = None
        self.connected = False
        if device_ip:
            self._setup_client(device_ip)
        
    def _setup_client(self, device_ip):
        """设置MQTT客户端"""
        try:
            self.device_ip = device_ip
            self.client = mqtt.Client()
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            log_manager.info(f"[MQTT] 初始化完成，Broker地址: {device_ip}:1883")
        except Exception as e:
            log_manager.error(f"[MQTT] 初始化失败: {e}")
            
    def connect(self, broker=None, port=1883):
        """连接到MQTT Broker（自动使用设备IP）
        
        Args:
            broker: Broker IP地址（如果为None则使用设备IP）
            port: MQTT端口，默认1883
        """
        # 如果没有指定broker，使用设备IP
        if broker is None:
            if not self.device_ip:
                error_msg = "未设置设备IP地址"
                log_manager.error(f"[MQTT] {error_msg}")
                return False, error_msg
            broker = self.device_ip
        
        # 如果client未初始化，先初始化
        if self.client is None:
            log_manager.info(f"[MQTT] 客户端未初始化，正在初始化...")
            self._setup_client(broker)
        
        try:
            log_manager.info(f"[MQTT] 正在连接到 {broker}:{port}...")
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            return True, f"已连接到MQTT Broker: {broker}:{port}"
        except Exception as e:
            error_msg = f"MQTT连接失败: {str(e)}"
            log_manager.error(f"[MQTT] {error_msg}")
            return False, error_msg

    def disconnect(self):
        """断开MQTT连接"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
            
    def _on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        if rc == 0:
            self.connected = True  # 关键：同步连接状态
            log_manager.info(f"[MQTT] 连接成功，已设置connected=True")
            print("MQTT连接成功")
        else:
            log_manager.error(f"[MQTT] 连接失败，错误码: {rc}")
            print(f"MQTT连接失败，错误码: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """断开回调"""
        self.connected = False
        print("MQTT连接已断开")
        
    def publish_track_command(self, track_id):
        """发布追踪控制命令"""
        if not self.connected or not self.client:
            return False, "MQTT未连接"
            
        try:
            # payload只有一个字节，对应配置文件里面的id字段
            payload = bytes([track_id])
            
            result = self.client.publish("track", payload)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                return True, f"已发送追踪指令，ID: {track_id}"
            else:
                return False, f"发送失败，错误码: {result.rc}"
                
        except Exception as e:
            return False, f"发送指令失败: {str(e)}"
            
    def get_status(self):
        """获取连接状态"""
        return {
            'connected': self.connected,
            'broker': self.broker,
            'port': self.port
        }
