# -*- coding: utf-8 -*-
"""
一键设备配置对话框
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QProgressBar, QTextEdit)
from PyQt5.QtCore import pyqtSignal, QThread
from smart_device_manager import SmartDeviceManager
from log_manager import LogManager

# 获取全局日志管理器实例
log_manager = LogManager()


class DeviceSetupDialog(QDialog):
    """设备配置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.device_manager = SmartDeviceManager()
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI界面"""
        self.setWindowTitle("设备配置向导")
        self.setFixedWidth(600)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 标题
        title_label = QLabel("🚀 一键设备配置")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; padding: 10px;")
        layout.addWidget(title_label)
        
        # 说明
        info_label = QLabel(
            "请确保设备已通过USB连接到电脑，然后点击'开始配置'按钮。\n"
            "系统将自动完成设备初始化、WiFi配置和SSH连接。"
        )
        info_label.setStyleSheet("padding: 10px; color: #7f8c8d;")
        layout.addWidget(info_label)
        
        # WiFi输入
        wifi_layout = QVBoxLayout()
        
        ssid_layout = QHBoxLayout()
        ssid_label = QLabel("WiFi名称:")
        ssid_label.setFixedWidth(100)
        ssid_layout.addWidget(ssid_label)
        self.ssid_input = QLineEdit()
        self.ssid_input.setPlaceholderText("例如: XBOTGO-5G")
        ssid_layout.addWidget(self.ssid_input)
        wifi_layout.addLayout(ssid_layout)
        
        password_layout = QHBoxLayout()
        password_label = QLabel("WiFi密码:")
        password_label.setFixedWidth(100)
        password_layout.addWidget(password_label)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("例如: xbotgogogo")
        password_layout.addWidget(self.password_input)
        wifi_layout.addLayout(password_layout)
        
        layout.addLayout(wifi_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 状态显示
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(200)
        self.status_text.setStyleSheet("background-color: #ecf0f1; font-family: 'Courier New';")
        layout.addWidget(self.status_text)
        
        # 结果IP显示
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #27ae60; padding: 10px;")
        self.result_label.setVisible(False)
        layout.addWidget(self.result_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("开始配置")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.start_button.clicked.connect(self.start_setup)
        button_layout.addWidget(self.start_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                font-size: 14px;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
    def log_message(self, message):
        """添加日志到状态文本框"""
        self.status_text.append(message)
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )
        
    def start_setup(self):
        """开始配置流程"""
        ssid = self.ssid_input.text().strip()
        password = self.password_input.text().strip()
        
        if not ssid or not password:
            self.log_message("❌ 错误: 请输入WiFi名称和密码")
            return
        
        # 禁用按钮
        self.start_button.setEnabled(False)
        self.start_button.setText("配置中...")
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定模式
        
        # 清空状态
        self.status_text.clear()
        self.result_label.setVisible(False)
        
        # 创建后台线程执行配置
        from threading import Thread
        from PyQt5.QtCore import QTimer
        from functools import partial
        import traceback
        
        def execute_setup():
            try:
                log_manager.info("[DIALOG] 开始执行配置线程...")
                success, msg, ip, rtsp_0, rtsp_1 = self.device_manager.full_auto_setup(ssid, password)
                log_manager.info(f"[DIALOG] 配置完成: success={success}, ip={ip}")
                
                if success:
                    # 成功情况 - 使用partial确保参数正确传递
                    log_manager.info("[DIALOG] 调用_on_setup_success")
                    callback = partial(self._on_setup_success, ip, rtsp_0, rtsp_1)
                    QTimer.singleShot(0, callback)
                else:
                    # 失败情况
                    log_manager.info(f"[DIALOG] 调用_on_setup_failure: {msg}")
                    callback = partial(self._on_setup_failure, msg)
                    QTimer.singleShot(0, callback)
                
            except Exception as e:
                error_trace = traceback.format_exc()
                log_manager.error(f"[DIALOG] 配置异常: {e}")
                callback = partial(self._on_setup_error, str(e), error_trace)
                QTimer.singleShot(0, callback)
        
        log_manager.info("[DIALOG] 启动配置线程")
        thread = Thread(target=execute_setup, daemon=True)
        thread.start()
    
    def _on_setup_success(self, ip, rtsp_0, rtsp_1):
        """配置成功的UI更新"""
        log_manager.info("[DIALOG] 执行_on_setup_success")
        try:
            self.progress_bar.setVisible(False)
            self.progress_bar.setRange(0, 100)  # 恢复默认范围
            self.start_button.setEnabled(True)
            self.start_button.setText("重新配置")
            self.result_label.setText(f"✅ 配置成功！\n设备IP: {ip}\nRTSP 0: {rtsp_0}\nRTSP 1: {rtsp_1}")
            self.result_label.setVisible(True)
            self.log_message(f"✅ 配置成功！设备IP: {ip}")
            
            # 延迟关闭对话框，让用户看到成功信息
            from PyQt5.QtCore import QTimer
            log_manager.info("[DIALOG] 设置1.5秒后关闭对话框的定时器")
            
            # 使用lambda包装确保调用正确
            def close_dialog():
                log_manager.info("[DIALOG] 定时器触发，准备关闭对话框")
                self.accept()
                log_manager.info("[DIALOG] 对话框已关闭")
            
            QTimer.singleShot(1500, close_dialog)
            log_manager.info("[DIALOG] 定时器已启动")
        except Exception as e:
            log_manager.error(f"[DIALOG] _on_setup_success 执行异常: {e}")

    def _on_setup_failure(self, msg):
        """配置失败的UI更新"""
        log_manager.info(f"[DIALOG] 执行_on_setup_failure: {msg}")
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)  # 恢复默认范围
        self.start_button.setEnabled(True)
        self.start_button.setText("重试")
        self.log_message(f"❌ 配置失败: {msg}")
    
    def _on_setup_error(self, error_msg, error_trace):
        """配置异常的UI更新"""
        log_manager.error(f"[DIALOG] 执行_on_setup_error: {error_msg}")
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)  # 恢复默认范围
        self.start_button.setEnabled(True)
        self.start_button.setText("重试")
        self.log_message(f" 异常: {error_msg}\n{error_trace}")

    def get_result(self):
        """获取配置结果"""
        return (
            self.device_manager.device_ip,
            self.device_manager.get_rtsp_urls()
        )
