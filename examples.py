# -*- coding: utf-8 -*-
"""
扩展开发示例 - 如何添加新的功能模块
"""

# ============================================
# 示例1: 添加新的性能监控指标
# ============================================

class CustomPerformanceMonitor:
    """自定义性能监控器示例"""
    
    def _get_temperature(self):
        """获取设备温度（示例）"""
        # 执行设备命令获取温度
        output = self._execute_command("cat /sys/class/thermal/thermal_zone0/temp")
        if output:
            try:
                # 假设输出是毫摄氏度，转换为摄氏度
                temp_c = int(output) / 1000.0
                return temp_c
            except:
                pass
        return 0.0
        
    def get_custom_metrics(self):
        """获取自定义指标"""
        return {
            'temperature': self._get_temperature(),
            # 可以添加更多指标
        }


# ============================================
# 示例2: 添加新的日志格式支持
# ============================================

import re

class CustomLogAnalyzer:
    """自定义日志分析器示例"""
    
    def __init__(self):
        # 添加新的正则表达式模式
        self.custom_patterns = {
            # 匹配自定义日志格式
            'custom_infer': re.compile(r"custom_infer_time:\s*(\d+\.\d+)\s*ms"),
            'custom_fps': re.compile(r"FPS:\s*(\d+\.\d+)"),
        }
        
    def parse_custom_log(self, log_file):
        """解析自定义格式的日志"""
        results = {}
        
        with open(log_file, 'r') as f:
            for line in f:
                # 匹配FPS
                fps_match = self.custom_patterns['custom_fps'].search(line)
                if fps_match:
                    fps = float(fps_match.group(1))
                    # 处理FPS数据
                    
                # 匹配推理时间
                infer_match = self.custom_patterns['custom_infer'].search(line)
                if infer_match:
                    infer_time = float(infer_match.group(1))
                    # 处理推理时间数据
                    
        return results


# ============================================
# 示例3: 添加新的MQTT控制命令
# ============================================

class CustomMQTTController:
    """自定义MQTT控制器示例"""
    
    def publish_custom_command(self, topic, command_data):
        """发送自定义命令"""
        if not self.connected or not self.client:
            return False, "MQTT未连接"
            
        try:
            # 发送JSON格式的命令
            import json
            payload = json.dumps(command_data)
            
            result = self.client.publish(topic, payload)
            
            if result.rc == 0:
                return True, f"命令已发送到 {topic}"
            else:
                return False, f"发送失败"
                
        except Exception as e:
            return False, str(e)
            
    def subscribe_topic(self, topic, callback=None):
        """订阅主题"""
        if self.client:
            self.client.subscribe(topic)
            if callback:
                self.client.message_callback_add(topic, callback)


# ============================================
# 示例4: 在主界面添加自定义标签页
# ============================================

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, 
                             QTextEdit, QGroupBox, QFormLayout, QLineEdit)

def create_custom_tab_example(self):
    """创建自定义标签页示例"""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    
    # 第一个组：控制区
    control_group = QGroupBox("自定义功能控制")
    control_layout = QFormLayout()
    
    custom_param = QLineEdit()
    control_layout.addRow("自定义参数:", custom_param)
    
    action_btn = QPushButton("执行自定义操作")
    # action_btn.clicked.connect(self.custom_action)
    control_layout.addRow(action_btn)
    
    control_group.setLayout(control_layout)
    layout.addWidget(control_group)
    
    # 第二个组：结果显示
    result_group = QGroupBox("操作结果")
    result_layout = QVBoxLayout()
    
    result_text = QTextEdit()
    result_text.setReadOnly(True)
    result_layout.addWidget(result_text)
    
    result_group.setLayout(result_layout)
    layout.addWidget(result_group)
    
    return widget


# ============================================
# 示例5: 添加数据导出功能
# ============================================

import csv
import json
from datetime import datetime

class DataExporter:
    """数据导出器示例"""
    
    def export_all_data(self, performance_data, log_data, config_data):
        """导出所有数据到报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"full_report_{timestamp}.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'performance': performance_data,
            'log_analysis': log_data,
            'configuration': config_data
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        return filename
        
    def export_to_excel(self, data_dict, filename="report.xlsx"):
        """导出到Excel（需要openpyxl库）"""
        try:
            from openpyxl import Workbook
            wb = Workbook()
            
            for sheet_name, data in data_dict.items():
                ws = wb.create_sheet(sheet_name)
                # 写入表头
                if isinstance(data, dict) and data:
                    headers = list(data.keys())
                    ws.append(headers)
                    # 写入数据行
                    # ... 根据数据结构处理
                    
            wb.save(filename)
            return True, filename
        except ImportError:
            return False, "需要安装 openpyxl: pip install openpyxl"


# ============================================
# 示例6: 添加实时视频预览功能
# ============================================

from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel
import cv2
import numpy as np

class VideoPreviewWidget(QLabel):
    """视频预览组件示例"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setText("等待视频流...")
        self.setAlignment(Qt.AlignCenter)
        
    def update_frame(self, frame):
        """更新视频帧"""
        if frame is None:
            return
            
        # 转换OpenCV图像到QImage
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qt_image = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        # 缩放并显示
        pixmap = QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatio)
        self.setPixmap(scaled_pixmap)


# ============================================
# 使用示例
# ============================================

if __name__ == "__main__":
    print("扩展开发示例文件")
    print("这些代码展示了如何:")
    print("1. 添加新的性能监控指标")
    print("2. 支持新的日志格式")
    print("3. 扩展MQTT控制命令")
    print("4. 创建自定义UI标签页")
    print("5. 实现数据导出功能")
    print("6. 添加视频预览组件")
    print("\n参考这些示例来定制你的功能！")
