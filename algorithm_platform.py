# -*- coding: utf-8 -*-
"""
算法验证上位机主程序
功能:模型管理、参数配置、性能监控、日志分析、视频源管理
"""

import sys
import os
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QGroupBox, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QProgressBar, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox, QDoubleSpinBox,
    QRadioButton, QButtonGroup, QDialog, QDialogButtonBox, QStatusBar,
    QMenuBar, QAction, QToolBar, QInputDialog, QFrame, QAbstractItemView
)

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt5.QtGui import QIcon, QFont, QTextCursor
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 配置matplotlib支持中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
import json
import re
import csv
import numpy as np
from datetime import datetime
from functools import partial
import traceback

# 导入自定义模块
from log_manager import LogManager
from device_manager import DeviceManager
from performance_monitor import PerformanceMonitor
from log_analyzer import LogAnalyzer
from video_manager import VideoManager
from mqtt_controller import MQTTController
from wifi_manager import WiFiManager
from smart_device_manager import SmartDeviceManager
from device_setup_dialog import DeviceSetupDialog
from rtmp_manager import RTMPManager

# 获取全局日志管理器
log_manager = LogManager()


class FileTransferWorker(QObject):
    """文件传输后台工作线程"""
    progress = pyqtSignal(int, str)  # 进度百分比, 状态消息
    finished = pyqtSignal(bool, str)  # 成功/失败, 消息
    
    def __init__(self, device_manager, operation_type, **kwargs):
        super().__init__()
        self.device_manager = device_manager
        self.operation_type = operation_type
        self.kwargs = kwargs
    
    def run(self):
        """执行文件传输操作"""
        try:
            log_manager.info(f"[WORKER] 开始执行{self.operation_type}操作")
            
            if self.operation_type == 'push_model':
                model_file = self.kwargs.get('model_file')
                device_ip = self.kwargs.get('device_ip')
                
                self.progress.emit(10, "正在连接设备...")
                success, msg = self.device_manager.push_model(model_file, device_ip, 'SSH')
                
                if success:
                    self.progress.emit(80, "模型推送成功,正在重启进程...")
                    restart_success, restart_msg = self.device_manager.restart_media_process(device_ip)
                    
                    if restart_success:
                        self.progress.emit(100, "完成")
                        self.finished.emit(True, f"{msg}\n✅ multi_media进程已自动重启")
                    else:
                        self.progress.emit(100, "完成")
                        self.finished.emit(True, f"{msg}\n⚠️ multi_media重启失败: {restart_msg}")
                else:
                    self.finished.emit(False, msg)
                    
            elif self.operation_type == 'push_config':
                config_file = self.kwargs.get('config_file')
                device_ip = self.kwargs.get('device_ip')
                
                self.progress.emit(10, "正在连接设备...")
                success, msg = self.device_manager.push_config(config_file, device_ip)
                
                if success:
                    self.progress.emit(80, "配置推送成功,正在重启进程...")
                    restart_success, restart_msg = self.device_manager.restart_media_process(device_ip)
                    
                    # 清理临时文件
                    if os.path.exists(config_file):
                        os.remove(config_file)
                    
                    if restart_success:
                        self.progress.emit(100, "完成")
                        self.finished.emit(True, f"{msg}\n✅ multi_media进程已自动重启,新配置已生效")
                    else:
                        self.progress.emit(100, "完成")
                        self.finished.emit(True, f"{msg}\n⚠️ multi_media重启失败: {restart_msg}")
                else:
                    # 清理临时文件
                    if os.path.exists(config_file):
                        os.remove(config_file)
                    self.finished.emit(False, msg)
                    
            elif self.operation_type == 'delete_model':
                model_name = self.kwargs.get('model_name')
                device_ip = self.kwargs.get('device_ip')
                
                self.progress.emit(10, "正在连接设备...")
                self.progress.emit(50, f"正在删除模型 {model_name}...")
                success, msg = self.device_manager.delete_model(model_name, device_ip)
                
                if success:
                    self.progress.emit(100, "完成")
                    self.finished.emit(True, msg)
                else:
                    self.finished.emit(False, msg)
                    
        except Exception as e:
            error_trace = traceback.format_exc()
            log_manager.error(f"[WORKER] {self.operation_type}操作异常: {e}", exc_info=True)
            self.finished.emit(False, f"{str(e)}\n{error_trace}")


class AlgorithmValidationPlatform(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("算法验证上位机平台")
        self.setGeometry(100, 100, 1600, 900)
        
        # 记录启动日志
        log_manager.info("=" * 60)
        log_manager.info("算法验证上位机平台启动")
        log_manager.info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_manager.info("=" * 60)
        
        # 初始化组件
        self.device_manager = DeviceManager()
        self.performance_monitor = PerformanceMonitor()
        self.log_analyzer = LogAnalyzer()
        self.video_manager = VideoManager()
        self.mqtt_controller = MQTTController()
        self.wifi_manager = WiFiManager()
        self.rtmp_manager = RTMPManager()
        
        # 设备连接状态
        self.device_connected = False
        self.ssh_available = False
        self.adb_available = False
        self.current_device_ip = None
        
        # 文件传输线程（防止被垃圾回收）
        self.transfer_worker = None
        self.transfer_thread = None
        
        # 状态栏
        self.statusBar().showMessage("就绪")
        
        # 创建菜单栏
        self.create_menu_bar()
        
        # 创建工具栏
        self.create_toolbar()
        
        # 创建主界面
        self.create_main_ui()
        
        # 定时器用于更新性能数据
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_performance_data)
        
        # 设备配置文件路径
        self.device_config_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            'device_config.json'
        )
        
        # 启动时自动连接设备（延迟500ms）
        QTimer.singleShot(500, self.auto_connect_device)

    def create_toolbar(self):
        """创建智能设备管理工具栏"""
        toolbar = QToolBar("设备管理")
        self.addToolBar(toolbar)
        
        # 一键配置按钮（主要入口）
        setup_action = QAction("🚀 一键配置设备", self)
        setup_action.setToolTip("自动完成：USB连接 → WiFi配置 → SSH设置 → RTSP生成")
        setup_action.triggered.connect(self.open_device_setup)
        toolbar.addAction(setup_action)
        
        toolbar.addSeparator()
        
        # 连接状态标签
        self.status_label = QLabel("未连接设备")
        self.status_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")
        toolbar.addWidget(self.status_label)
        
        toolbar.addSeparator()
        
        # RTSP地址显示
        self.rtsp_label_0 = QLabel("RTSP 0: N/A")
        self.rtsp_label_1 = QLabel("RTSP 1: N/A")
        self.rtsp_label_0.setStyleSheet("color: blue; padding: 5px;")
        self.rtsp_label_1.setStyleSheet("color: blue; padding: 5px;")
        toolbar.addWidget(self.rtsp_label_0)
        toolbar.addWidget(self.rtsp_label_1)
        
        # 保存引用以便后续更新
        self.toolbar = toolbar

    def open_device_setup(self):
        """打开设备配置对话框"""
        dialog = DeviceSetupDialog(self)
        
        if dialog.exec_() == QDialog.Accepted:
            # 获取配置结果
            device_ip, (rtsp_0, rtsp_1) = dialog.get_result()
            
            # 获取WiFi信息（从对话框，使用正确的属性名）
            wifi_ssid = dialog.ssid_input.text() if hasattr(dialog, 'ssid_input') else ''
            wifi_password = dialog.password_input.text() if hasattr(dialog, 'password_input') else ''
            
            if device_ip:
                # 更新状态
                self.current_device_ip = device_ip
                self.device_connected = True
                self.ssh_available = True
                
                # 更新状态显示
                self.status_label.setText(f"✅ {device_ip}")
                self.status_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
                
                # 更新RTSP显示
                if rtsp_0 and rtsp_1:
                    self.rtsp_label_0.setText(f"RTSP 0: {rtsp_0}")
                    self.rtsp_label_1.setText(f"RTSP 1: {rtsp_1}")
                
                # 更新视频源管理页面的设备IP显示
                self.rtsp_device_ip_label.setText(device_ip)
                self.rtsp_device_ip_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
                
                # 保存设备配置（包括WiFi信息）
                self.save_device_config(device_ip, rtsp_0, rtsp_1, wifi_ssid, wifi_password)
                
                # 自动初始化MQTT（使用设备IP作为Broker）
                log_manager.info(f"[AUTO] 正在自动连接MQTT Broker: {device_ip}:1883")
                self._auto_connect_mqtt(device_ip)
                
                # 更新其他组件的设备IP
                self.device_manager.ssh_client = None  # 强制重新连接
                
                log_manager.info(f"[AUTO] 设备配置完成，IP: {device_ip}")
                
                QMessageBox.information(
                    self, 
                    "配置成功", 
                    f"设备配置已完成！\n\n"
                    f"设备IP: {device_ip}\n"
                    f"RTSP 0: {rtsp_0}\n"
                    f"RTSP 1: {rtsp_1}\n"
                    f"MQTT: 已自动连接到 {device_ip}:1883\n\n"
                    f"✅ 配置已保存，下次启动时将自动连接\n\n"
                    f"现在可以使用所有功能了。"
                )

    def _auto_connect_mqtt(self, device_ip):
        """自动连接MQTT（用户无感知）"""
        try:
            # 设置设备IP到MQTT控制器
            self.mqtt_controller.device_ip = device_ip
            
            # 自动连接
            success, msg = self.mqtt_controller.connect(broker=device_ip, port=1883)
            
            if success:
                log_manager.info(f"[AUTO] MQTT自动连接成功: {msg}")
                self.mqtt_status_label.setText(f"✅ MQTT: 已连接\n📡 Broker: {device_ip}:1883")
                self.mqtt_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #d4edda; 
                    border-radius: 5px;
                    color: #155724;
                    font-weight: bold;
                """)
                self.statusBar().showMessage(f"MQTT已连接: {device_ip}:1883", 3000)
            else:
                log_manager.warning(f"[AUTO] MQTT连接失败: {msg}，但不影响其他功能")
                self.mqtt_status_label.setText(f"❌ MQTT: 连接失败\n💡 提示: {msg}")
                self.mqtt_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #fff3cd; 
                    border-radius: 5px;
                    color: #856404;
                """)
                # 不显示错误对话框，静默失败即可
                
        except Exception as e:
            log_manager.warning(f"[AUTO] MQTT自动连接异常: {e}")
            self.mqtt_status_label.setText(f"❌ MQTT: 异常\n💡 提示: {str(e)}")
            self.mqtt_status_label.setStyleSheet("""
                padding: 15px; 
                background-color: #f8d7da; 
                border-radius: 5px;
                color: #721c24;
            """)
            # 不影响主流程，仅记录日志

    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件')
        
        # 添加清除设备配置选项
        clear_config_action = QAction('清除设备配置', self)
        clear_config_action.setToolTip('清除保存的设备配置，下次启动时需要重新配置')
        clear_config_action.triggered.connect(self.clear_device_config)
        file_menu.addAction(clear_config_action)
        
        file_menu.addSeparator()
        
        export_action = QAction('导出报告', self)
        export_action.triggered.connect(self.export_report)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu('工具')
        
        # 添加日志查看器
        from log_viewer import LogViewerDialog
        log_viewer_action = QAction('查看运行日志', self)
        log_viewer_action.triggered.connect(lambda: self.open_log_viewer())
        tools_menu.addAction(log_viewer_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu('帮助')
        
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def open_log_viewer(self):
        """打开日志查看器"""
        from log_viewer import LogViewerDialog
        dialog = LogViewerDialog(self)
        dialog.exec_()
        
    def create_main_ui(self):
        """创建主界面"""
        # 创建标签页
        tab_widget = QTabWidget()
        self.setCentralWidget(tab_widget)
        
        # 添加各个功能标签页
        tab_widget.addTab(self.create_model_config_tab(), "模型与配置")  # 合并模型管理和参数配置
        tab_widget.addTab(self.create_rtmp_tab(), "RTMP直播")  # 新增
        tab_widget.addTab(self.create_performance_tab(), "性能监控")  # 包含算法控制和进程控制
        tab_widget.addTab(self.create_log_analysis_tab(), "日志分析")
        tab_widget.addTab(self.create_video_tab(), "视频源管理")
        # 移除独立的"算法控制"标签页，已合并到性能监控页面

    def create_model_config_tab(self):
        """创建模型与配置合并标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ========== 上半部分：模型管理 ==========
        model_group = QGroupBox("📦 模型文件管理")
        model_layout = QVBoxLayout()
        
        # 模型文件选择
        file_select_layout = QHBoxLayout()
        self.model_file_edit = QLineEdit()
        self.model_file_edit.setReadOnly(True)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_model_file)
        file_select_layout.addWidget(QLabel("RKNN模型:"))
        file_select_layout.addWidget(self.model_file_edit)
        file_select_layout.addWidget(browse_btn)
        model_layout.addLayout(file_select_layout)
        
        # 推送按钮
        push_model_btn = QPushButton("📤 推送模型到设备")
        push_model_btn.clicked.connect(self.push_model_to_device)
        push_model_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold;")
        model_layout.addWidget(push_model_btn)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # 当前模型列表（带删除功能）
        list_group = QGroupBox("📋 已部署模型")
        list_layout = QVBoxLayout()
        
        self.model_table = QTableWidget()
        self.model_table.setColumnCount(4)
        self.model_table.setHorizontalHeaderLabels(["模型名称", "大小", "修改时间", "操作"])
        self.model_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        list_layout.addWidget(self.model_table)
        
        refresh_btn = QPushButton("🔄 刷新模型列表")
        refresh_btn.clicked.connect(self.refresh_model_list)
        list_layout.addWidget(refresh_btn)
        
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        # ========== 分隔线 ==========
        separator = QLabel()
        separator.setFrameStyle(QFrame.HLine | QFrame.Sunken)
        layout.addWidget(separator)
        
        # ========== 下半部分：参数配置 ==========
        config_group = QGroupBox("⚙️ 配置文件管理")
        config_layout = QVBoxLayout()
        
        # 配置文件选择
        config_file_layout = QHBoxLayout()
        self.config_file_edit = QLineEdit()
        self.config_file_edit.setReadOnly(True)
        config_browse_btn = QPushButton("浏览...")
        config_browse_btn.clicked.connect(self.browse_config_file)
        config_file_layout.addWidget(QLabel("配置文件:"))
        config_file_layout.addWidget(self.config_file_edit)
        config_file_layout.addWidget(config_browse_btn)
        config_layout.addLayout(config_file_layout)
        
        load_config_btn = QPushButton("📂 加载配置")
        load_config_btn.clicked.connect(self.load_config)
        config_layout.addWidget(load_config_btn)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # 配置编辑器
        edit_group = QGroupBox("📝 配置编辑器")
        edit_layout = QVBoxLayout()
        
        self.config_text_edit = QTextEdit()
        self.config_text_edit.setFont(QFont("Consolas", 10))
        edit_layout.addWidget(self.config_text_edit)
        
        btn_layout = QHBoxLayout()
        save_local_btn = QPushButton("💾 保存到本地")
        save_local_btn.clicked.connect(self.save_config_local)
        btn_layout.addWidget(save_local_btn)
        
        push_config_btn = QPushButton("📤 推送到设备")
        push_config_btn.clicked.connect(self.push_config_to_device)
        push_config_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px; font-weight: bold;")
        btn_layout.addWidget(push_config_btn)
        
        edit_layout.addLayout(btn_layout)
        edit_group.setLayout(edit_layout)
        layout.addWidget(edit_group)
        
        return widget
        
    def create_model_tab(self):
        """创建模型管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 模型文件选择组
        model_group = QGroupBox("模型文件管理")
        model_layout = QFormLayout()
        
        self.model_file_edit = QLineEdit()
        self.model_file_edit.setReadOnly(True)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_model_file)
        model_file_layout = QHBoxLayout()
        model_file_layout.addWidget(self.model_file_edit)
        model_file_layout.addWidget(browse_btn)
        model_layout.addRow("RKNN模型:", model_file_layout)
        
        push_model_btn = QPushButton("推送模型到设备")
        push_model_btn.clicked.connect(self.push_model_to_device)
        push_model_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        model_layout.addRow(push_model_btn)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # 当前模型列表
        list_group = QGroupBox("已部署模型")
        list_layout = QVBoxLayout()
        
        # 添加oem分区占用信息显示
        self.oem_usage_label = QLabel("加载中...")
        self.oem_usage_label.setStyleSheet("""
            padding: 8px; 
            background-color: #e3f2fd; 
            border-radius: 3px;
            color: #1976d2;
            font-weight: bold;
        """)
        self.oem_usage_label.setWordWrap(True)
        list_layout.addWidget(self.oem_usage_label)
        
        self.model_table = QTableWidget()
        self.model_table.setColumnCount(3)
        self.model_table.setHorizontalHeaderLabels(["模型名称", "大小", "修改时间"])
        self.model_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        list_layout.addWidget(self.model_table)
        
        refresh_btn = QPushButton("刷新模型列表")
        refresh_btn.clicked.connect(self.refresh_model_list)
        list_layout.addWidget(refresh_btn)
        
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        return widget
        
    def create_performance_tab(self):
        """创建性能监控标签页（包含算法控制和进程控制）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 控制面板
        control_group = QGroupBox("监控控制")
        control_layout = QFormLayout()
        
        self.monitor_interval_spin = QSpinBox()
        self.monitor_interval_spin.setRange(1, 10)
        self.monitor_interval_spin.setValue(2)
        control_layout.addRow("采样间隔(秒):", self.monitor_interval_spin)
        
        self.ddr_freq_spin = QSpinBox()
        self.ddr_freq_spin.setRange(1000, 3000)
        self.ddr_freq_spin.setValue(1848)
        control_layout.addRow("DDR频率(MHz):", self.ddr_freq_spin)
        
        # 创建单个按钮，根据状态切换文本
        self.monitor_btn = QPushButton("开始监控")
        self.monitor_btn.clicked.connect(self.toggle_monitoring)
        self.monitor_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        control_layout.addRow(self.monitor_btn)
        
        # 监控状态标记
        self.is_monitoring = False
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # MQTT状态显示（只读，自动连接）
        mqtt_group = QGroupBox("MQTT状态")
        mqtt_layout = QVBoxLayout()
        
        self.mqtt_status_label = QLabel("🔌 MQTT: 未连接\n💡 提示: 设备配置后将自动连接MQTT")
        self.mqtt_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
        """)
        self.mqtt_status_label.setWordWrap(True)
        mqtt_layout.addWidget(self.mqtt_status_label)
        
        mqtt_group.setLayout(mqtt_layout)
        layout.addWidget(mqtt_group)
        
        # 追踪模式选择（使用单个按钮切换状态）
        track_group = QGroupBox("追踪模式")
        track_layout = QFormLayout()
        
        self.track_mode_combo = QComboBox()
        # 从配置文件加载模式
        self.load_track_modes()
        track_layout.addRow("追踪模式:", self.track_mode_combo)
        
        # 创建单个按钮，根据状态切换文本
        self.track_btn = QPushButton("启动追踪")
        self.track_btn.clicked.connect(self.toggle_tracking)
        self.track_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        track_layout.addRow(self.track_btn)
        
        # 追踪状态标记
        self.is_tracking = False
        
        track_group.setLayout(track_layout)
        layout.addWidget(track_group)
        
        # 进程控制
        process_group = QGroupBox("进程控制")
        process_layout = QHBoxLayout()
        
        restart_process_btn = QPushButton("重启multi_media进程")
        restart_process_btn.clicked.connect(self.restart_media_process)
        restart_process_btn.setStyleSheet("background-color: #FF9800; color: white;")
        process_layout.addWidget(restart_process_btn)
        
        kill_process_btn = QPushButton("停止multi_media进程")
        kill_process_btn.clicked.connect(self.kill_media_process)
        kill_process_btn.setStyleSheet("background-color: #f44336; color: white;")
        process_layout.addWidget(kill_process_btn)
        
        process_group.setLayout(process_layout)
        layout.addWidget(process_group)
        
        # 实时数据显示
        data_group = QGroupBox("实时数据")
        data_layout = QVBoxLayout()
        
        self.perf_table = QTableWidget()
        self.perf_table.setColumnCount(2)
        self.perf_table.setHorizontalHeaderLabels(["指标", "数值"])
        self.perf_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        data_layout.addWidget(self.perf_table)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # 图表区域
        chart_group = QGroupBox("性能趋势图")
        chart_layout = QVBoxLayout()
        
        self.perf_figure = Figure(figsize=(10, 4))
        self.perf_canvas = FigureCanvas(self.perf_figure)
        chart_layout.addWidget(self.perf_canvas)
        
        chart_group.setLayout(chart_layout)
        layout.addWidget(chart_group)
        
        return widget
        
    def create_log_analysis_tab(self):
        """创建日志分析标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ========== 上半部分：日志文件选择 ==========
        file_group = QGroupBox("📄 日志文件选择")
        file_layout = QVBoxLayout()
        
        # 日志文件输入框和按钮
        file_select_layout = QHBoxLayout()
        self.log_file_edit = QLineEdit()
        self.log_file_edit.setReadOnly(True)
        log_browse_btn = QPushButton("本地浏览...")
        log_browse_btn.clicked.connect(self.browse_log_file)
        device_log_btn = QPushButton("从设备选择...")
        device_log_btn.clicked.connect(self.load_device_logs)
        device_log_btn.setStyleSheet("background-color: #2196F3; color: white;")
        
        file_select_layout = QHBoxLayout()
        file_select_layout.addWidget(QLabel("日志文件:"))
        file_select_layout.addWidget(self.log_file_edit)
        file_select_layout.addWidget(log_browse_btn)
        file_select_layout.addWidget(device_log_btn)
        file_layout.addLayout(file_select_layout)
        
        # 分析按钮
        analyze_btn = QPushButton(" 分析日志")
        analyze_btn.clicked.connect(self.analyze_log)
        analyze_btn.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 10px;")
        file_layout.addWidget(analyze_btn)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # ========== 分隔线 ==========
        separator = QLabel()
        separator.setFrameStyle(QFrame.HLine | QFrame.Sunken)
        layout.addWidget(separator)
        
        # ========== 下半部分：设备日志列表 ==========
        list_group = QGroupBox("📋 设备日志文件列表")
        list_layout = QVBoxLayout()
        
        self.device_log_table = QTableWidget()
        self.device_log_table.setColumnCount(4)
        self.device_log_table.setHorizontalHeaderLabels(["日志文件名", "大小", "修改时间", "操作"])
        self.device_log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.device_log_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 8px;
                border: 1px solid #d0d0d0;
                font-weight: bold;
            }
        """)
        list_layout.addWidget(self.device_log_table)
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton(" 刷新日志列表")
        refresh_btn.clicked.connect(self.load_device_logs)
        btn_layout.addWidget(refresh_btn)
        
        list_layout.addLayout(btn_layout)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        # ========== 分隔线 ==========
        separator2 = QLabel()
        separator2.setFrameStyle(QFrame.HLine | QFrame.Sunken)
        layout.addWidget(separator2)
        
        # ========== 分析结果 ==========
        result_group = QGroupBox("📊 分析结果")
        result_layout = QVBoxLayout()
        
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(7)
        self.result_table.setHorizontalHeaderLabels([
            "模型名称", 
            "推理平均(ms)", 
            "总耗时平均(ms)", 
            "最大耗时(ms)",
            "帧数",
            "推理标准差(ms)",
            "总耗时标准差(ms)"
        ])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 8px;
                border: 1px solid #d0d0d0;
                font-weight: bold;
            }
        """)
        result_layout.addWidget(self.result_table)
        
        export_csv_btn = QPushButton("💾 导出CSV")
        export_csv_btn.clicked.connect(self.export_csv)
        result_layout.addWidget(export_csv_btn)
        
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)
        
        # 图表显示
        plot_group = QGroupBox("📈 耗时曲线")
        plot_layout = QVBoxLayout()
        
        self.log_figure = Figure(figsize=(10, 5))
        self.log_canvas = FigureCanvas(self.log_figure)
        plot_layout.addWidget(self.log_canvas)
        
        # 导出图片按钮
        export_plot_btn = QPushButton("💾 导出图片")
        export_plot_btn.clicked.connect(self.export_log_plot)
        export_plot_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        plot_layout.addWidget(export_plot_btn)
        
        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        return widget
        
    def create_video_tab(self):
        """创建视频源管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # RTSP配置
        rtsp_group = QGroupBox("RTSP流配置")
        rtsp_layout = QFormLayout()
        
        # 显示当前设备IP（只读）
        self.rtsp_device_ip_label = QLabel("未连接设备")
        self.rtsp_device_ip_label.setStyleSheet("color: #7f8c8d; padding: 5px;")
        rtsp_layout.addRow("设备IP:", self.rtsp_device_ip_label)
        
        self.rtsp_channel1 = QCheckBox("通道0 (rtsp://IP/live/0)")
        self.rtsp_channel1.setChecked(True)
        rtsp_layout.addRow(self.rtsp_channel1)
        
        self.rtsp_channel2 = QCheckBox("通道1 (rtsp://IP/live/1)")
        rtsp_layout.addRow(self.rtsp_channel2)
        
        connect_rtsp_btn = QPushButton("连接RTSP流")
        connect_rtsp_btn.clicked.connect(self.connect_rtsp)
        rtsp_layout.addRow(connect_rtsp_btn)
        
        rtsp_group.setLayout(rtsp_layout)
        layout.addWidget(rtsp_group)
        
        # 本地视频上传
        local_group = QGroupBox("本地视频管理")
        local_layout = QFormLayout()
        
        self.video_file_edit = QLineEdit()
        self.video_file_edit.setReadOnly(True)
        video_browse_btn = QPushButton("浏览...")
        video_browse_btn.clicked.connect(self.browse_video_file)
        video_file_layout = QHBoxLayout()
        video_file_layout.addWidget(self.video_file_edit)
        video_file_layout.addWidget(video_browse_btn)
        local_layout.addRow("视频文件:", video_file_layout)
        
        upload_video_btn = QPushButton("上传视频到设备")
        upload_video_btn.clicked.connect(self.upload_video_to_device)
        local_layout.addRow(upload_video_btn)
        
        local_group.setLayout(local_layout)
        layout.addWidget(local_group)
        
        # 视频源切换
        source_group = QGroupBox("视频源选择")
        source_layout = QFormLayout()
        
        self.video_source_combo = QComboBox()
        self.video_source_combo.addItems(["本地视频(/userdata)", "RTSP摄像头流"])
        source_layout.addRow("视频源:", self.video_source_combo)
        
        apply_source_btn = QPushButton("应用视频源设置")
        apply_source_btn.clicked.connect(self.apply_video_source)
        source_layout.addRow(apply_source_btn)
        
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        return widget
        
    def create_rtmp_tab(self):
        """创建RTMP直播标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # RTMP服务器配置组
        rtmp_group = QGroupBox("RTMP服务器配置")
        rtmp_layout = QFormLayout()
        
        self.rtmp_url_edit = QLineEdit("rtmp://192.168.17.108/live/test")
        self.rtmp_url_edit.setPlaceholderText("例如: rtmp://192.168.17.108/live/test")
        rtmp_layout.addRow("服务器地址:", self.rtmp_url_edit)
        
        self.rtmp_quality_combo = QComboBox()
        self.rtmp_quality_combo.addItems(["720P (流畅)", "1080P (高清)"])
        self.rtmp_quality_combo.setCurrentIndex(0)
        rtmp_layout.addRow("画质选择:", self.rtmp_quality_combo)
        
        rtmp_group.setLayout(rtmp_layout)
        layout.addWidget(rtmp_group)
        
        # 推流控制组
        control_group = QGroupBox("推流控制")
        control_layout = QVBoxLayout()
        
        # 状态显示
        self.rtmp_status_label = QLabel("📺 RTMP推流状态: 未启动")
        self.rtmp_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
            font-size: 14px;
        """)
        self.rtmp_status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.rtmp_status_label)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        
        start_stream_btn = QPushButton("▶️ 开始直播")
        start_stream_btn.clicked.connect(self.start_rtmp_streaming)
        start_stream_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        btn_layout.addWidget(start_stream_btn)
        
        stop_stream_btn = QPushButton("⏹️ 停止直播")
        stop_stream_btn.clicked.connect(self.stop_rtmp_streaming)
        stop_stream_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        btn_layout.addWidget(stop_stream_btn)
        
        control_layout.addLayout(btn_layout)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 使用说明
        help_group = QGroupBox("使用说明")
        help_layout = QVBoxLayout()
        help_text = QLabel(
            "• 选择画质后点击'开始直播'即可推流\n"
            "• 720P适合网络带宽有限的场景\n"
            "• 1080P提供高清画质\n"
            "• 推流过程中可随时停止\n"
            "• 确保设备已连接到网络"
        )
        help_text.setStyleSheet("color: #7f8c8d; padding: 10px;")
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        help_group.setLayout(help_layout)
        layout.addWidget(help_group)
        
        return widget
        
    def start_rtmp_streaming(self):
        """开始RTMP推流"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            log_manager.warning("[OPERATION] RTMP推流失败：设备未连接")
            return
        
        rtmp_url = self.rtmp_url_edit.text().strip()
        if not rtmp_url:
            QMessageBox.warning(self, "错误", "请输入RTMP服务器地址")
            return
        
        # 获取画质选择
        quality_index = self.rtmp_quality_combo.currentIndex()
        quality = '720p' if quality_index == 0 else '1080p'
        
        log_manager.info(f"[OPERATION] 开始RTMP推流: URL={rtmp_url}, Quality={quality}")
        
        reply = QMessageBox.question(
            self, 
            "确认", 
            f"确定要开始RTMP推流吗？\n\n服务器: {rtmp_url}\n画质: {quality}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        self.statusBar().showMessage(f"正在启动RTMP推流 ({quality})...")
        self.rtmp_status_label.setText("📺 RTMP推流状态: 启动中...")
        self.rtmp_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #fff3cd; 
            border-radius: 5px;
            color: #856404;
            font-size: 14px;
        """)
        
        try:
            # 设置设备IP到RTMP管理器
            self.rtmp_manager.device_ip = self.current_device_ip
            
            # 执行推流命令
            success, msg = self.rtmp_manager.start_streaming(rtmp_url, quality)
            
            if success:
                log_manager.info(f"[RTMP] 推流启动成功: {msg}")
                self.rtmp_status_label.setText(f"✅ RTMP推流状态: 直播中 ({quality})")
                self.rtmp_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #d4edda; 
                    border-radius: 5px;
                    color: #155724;
                    font-size: 14px;
                    font-weight: bold;
                """)
                QMessageBox.information(self, "成功", f"{msg}\n\nRTMP推流已启动！")
                self.statusBar().showMessage(f"RTMP推流已启动 ({quality})", 3000)
            else:
                log_manager.error(f"[RTMP] 推流启动失败: {msg}")
                self.rtmp_status_label.setText("❌ RTMP推流状态: 启动失败")
                self.rtmp_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #f8d7da; 
                    border-radius: 5px;
                    color: #721c24;
                    font-size: 14px;
                """)
                QMessageBox.critical(self, "失败", msg)
                self.statusBar().showMessage("RTMP推流启动失败", 3000)
                
        except Exception as e:
            error_msg = f"RTMP停止推流异常: {str(e)}"
            log_manager.error(f"[RTMP] {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)
            self.rtmp_status_label.setText("❌ RTMP推流状态: 异常")
            self.statusBar().showMessage("RTMP停止推流异常", 3000)
    
    def stop_rtmp_streaming(self):
        """停止RTMP推流"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        log_manager.info("[OPERATION] 停止RTMP推流")
        
        reply = QMessageBox.question(
            self, 
            "确认", 
            "确定要停止RTMP推流吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        self.statusBar().showMessage("正在停止RTMP推流...")
        self.rtmp_status_label.setText("📺 RTMP推流状态: 停止中...")
        self.rtmp_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #fff3cd; 
            border-radius: 5px;
            color: #856404;
            font-size: 14px;
        """)
        
        try:
            # 设置设备IP到RTMP管理器
            self.rtmp_manager.device_ip = self.current_device_ip
            
            # 执行停止命令
            success, msg = self.rtmp_manager.stop_streaming()
            
            if success:
                log_manager.info(f"[RTMP] 推流停止成功: {msg}")
                self.rtmp_status_label.setText("⏹️ RTMP推流状态: 已停止")
                self.rtmp_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #ecf0f1; 
                    border-radius: 5px;
                    color: #7f8c8d;
                    font-size: 14px;
                """)
                QMessageBox.information(self, "成功", msg)
                self.statusBar().showMessage("RTMP推流已停止", 3000)
            else:
                log_manager.error(f"[RTMP] 推流停止失败: {msg}")
                self.rtmp_status_label.setText("❌ RTMP推流状态: 停止失败")
                self.rtmp_status_label.setStyleSheet("""
                    padding: 15px; 
                    background-color: #f8d7da; 
                    border-radius: 5px;
                    color: #721c24;
                    font-size: 14px;
                """)
                QMessageBox.critical(self, "失败", msg)
                self.statusBar().showMessage("RTMP推流停止失败", 3000)
                
        except Exception as e:
            error_msg = f"RTMP停止推流异常: {str(e)}"
            log_manager.error(f"[RTMP] {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)
            self.rtmp_status_label.setText("❌ RTMP推流状态: 异常")
            self.statusBar().showMessage("RTMP停止推流异常", 3000)

    def create_control_tab(self):
        """创建算法控制标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # MQTT状态显示（只读，自动连接）
        mqtt_group = QGroupBox("MQTT状态")
        mqtt_layout = QVBoxLayout()
        
        self.mqtt_status_label = QLabel("🔌 MQTT: 未连接\n💡 提示: 设备配置后将自动连接MQTT")
        self.mqtt_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
        """)
        self.mqtt_status_label.setWordWrap(True)
        mqtt_layout.addWidget(self.mqtt_status_label)
        
        mqtt_group.setLayout(mqtt_layout)
        layout.addWidget(mqtt_group)
        
        # 追踪模式选择（移除了停止追踪选项）
        track_group = QGroupBox("追踪模式")
        track_layout = QFormLayout()
        
        self.track_mode_combo = QComboBox()
        # 从配置文件加载模式
        self.load_track_modes()
        track_layout.addRow("追踪模式:", self.track_mode_combo)
        
        start_track_btn = QPushButton("启动追踪")
        start_track_btn.clicked.connect(self.start_tracking)
        start_track_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        track_layout.addRow(start_track_btn)
        
        stop_track_btn = QPushButton("停止追踪")
        stop_track_btn.clicked.connect(self.stop_tracking)
        stop_track_btn.setStyleSheet("background-color: #f44336; color: white; padding: 10px;")
        track_layout.addRow(stop_track_btn)
        
        track_group.setLayout(track_layout)
        layout.addWidget(track_group)
        
        # 进程控制
        process_group = QGroupBox("进程控制")
        process_layout = QHBoxLayout()
        
        restart_process_btn = QPushButton("重启multi_media进程")
        restart_process_btn.clicked.connect(self.restart_media_process)
        restart_process_btn.setStyleSheet("background-color: #FF9800; color: white;")
        process_layout.addWidget(restart_process_btn)
        
        kill_process_btn = QPushButton("停止multi_media进程")
        kill_process_btn.clicked.connect(self.kill_media_process)
        kill_process_btn.setStyleSheet("background-color: #f44336; color: white;")
        process_layout.addWidget(kill_process_btn)
        
        process_group.setLayout(process_layout)
        layout.addWidget(process_group)
        
        return widget
    
    # ==================== 槽函数实现 ====================
    
    def browse_model_file(self):
        """浏览选择模型文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择RKNN模型文件", "", "RKNN Files (*.rknn)")
        if file_name:
            self.model_file_edit.setText(file_name)
            log_manager.info(f"[OPERATION] 选择模型文件: {file_name}")
            
    def push_model_to_device(self):
        """推送模型到设备(使用后台线程)"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            log_manager.warning("[OPERATION] 推送模型失败：设备未连接")
            return
        
        model_file = self.model_file_edit.text()
        if not model_file or not os.path.exists(model_file):
            QMessageBox.warning(self, "错误", "请选择有效的模型文件")
            log_manager.warning("[OPERATION] 推送模型失败：未选择有效文件")
            return
        
        ip = self.current_device_ip
        
        log_manager.info(f"[OPERATION] 准备推送模型: {os.path.basename(model_file)} -> {ip}")
        
        reply = QMessageBox.question(self, "确认", 
                                    f"确定要推送模型 {os.path.basename(model_file)} 到设备 {ip} 吗？\n这将覆盖原有文件。",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            log_manager.info(f"[OPERATION] 用户取消了推送操作")
            return
        
        # 创建进度对话框
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("推送模型")
        progress_dialog.setModal(True)
        progress_dialog.setFixedSize(400, 150)
        
        progress_layout = QVBoxLayout(progress_dialog)
        
        status_label = QLabel("正在准备推送...")
        status_label.setStyleSheet("font-size: 12px; padding: 10px;")
        progress_layout.addWidget(status_label)
        
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_layout.addWidget(progress_bar)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setEnabled(False)  # 暂时不允许取消
        progress_layout.addWidget(cancel_btn)
        
        progress_dialog.show()
        self.statusBar().showMessage(f"正在推送模型到 {ip}...")
        log_manager.info(f"[DEVICE] 开始推送模型: {model_file} -> {ip}")
        
        # 创建后台线程（保存为实例属性，防止被垃圾回收）
        self.transfer_worker = FileTransferWorker(
            self.device_manager,
            'push_model',
            model_file=model_file,
            device_ip=ip
        )
        
        self.transfer_thread = QThread()
        self.transfer_worker.moveToThread(self.transfer_thread)
        
        # 连接信号
        self.transfer_thread.started.connect(self.transfer_worker.run)
        self.transfer_worker.progress.connect(lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg))
        self.transfer_worker.finished.connect(lambda success, msg: self._on_push_model_finished(success, msg, progress_dialog, self.transfer_thread, ip))
        
        # 启动线程
        self.transfer_thread.start()
    
    def _update_progress(self, progress_bar, status_label, percent, msg):
        """更新进度显示"""
        progress_bar.setValue(percent)
        status_label.setText(msg)
    
    def _on_push_model_finished(self, success, msg, progress_dialog, thread, ip):
        """模型推送完成回调"""
        progress_dialog.close()
        thread.quit()
        thread.wait()
        
        # 清理线程资源
        self.transfer_worker = None
        self.transfer_thread = None
        
        if success:
            log_manager.info(f"[DEVICE] 模型推送成功: {msg}")
            QMessageBox.information(
                self,
                "推送成功",
                f"模型已成功推送到 {ip}！"
            )
        else:
            log_manager.error(f"[DEVICE] 模型推送失败: {msg}")
            QMessageBox.critical(
                self,
                "推送失败",
                f"模型推送失败！\n{msg}"
            )
    
    def push_config(self, config_file, ip):
        """推送配置文件"""
        temp_file = self._save_config_to_temp(config_file)
        if not temp_file:
            return
        
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("推送配置文件")
        progress_dialog.setFixedSize(400, 100)
        progress_dialog.setModal(True)
        progress_dialog.setWindowFlags(Qt.WindowTitleHint | Qt.WindowSystemMenuHint)
        
        progress_layout = QVBoxLayout(progress_dialog)
        progress_bar = QProgressBar(progress_dialog)
        progress_bar.setRange(0, 100)
        progress_layout.addWidget(progress_bar)
        
        status_label = QLabel(progress_dialog)
        status_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(status_label)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setEnabled(False)  # 暂时不允许取消
        progress_layout.addWidget(cancel_btn)
        
        progress_dialog.show()
        self.statusBar().showMessage(f"正在推送配置文件到 {ip}...")
        
        # 创建后台线程（保存为实例属性，防止被垃圾回收）
        self.transfer_worker = FileTransferWorker(
            self.device_manager,
            'push_config',
            config_file=temp_file,
            device_ip=ip
        )
        
        self.transfer_thread = QThread()
        self.transfer_worker.moveToThread(self.transfer_thread)
        
        # 连接信号
        self.transfer_thread.started.connect(self.transfer_worker.run)
        self.transfer_worker.progress.connect(lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg))
        self.transfer_worker.finished.connect(lambda success, msg: self._on_push_config_finished(success, msg, progress_dialog, self.transfer_thread))
        
        # 启动线程
        self.transfer_thread.start()
    
    def delete_model(self, ip, model_name):
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("删除模型")
        progress_dialog.setFixedSize(400, 100)
        progress_dialog.setModal(True)
        progress_dialog.setWindowFlags(Qt.WindowTitleHint | Qt.WindowSystemMenuHint)
        
        progress_layout = QVBoxLayout(progress_dialog)
        progress_bar = QProgressBar(progress_dialog)
        progress_bar.setRange(0, 100)
        progress_layout.addWidget(progress_bar)
        
        status_label = QLabel(progress_dialog)
        status_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(status_label)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setEnabled(False)
        progress_layout.addWidget(cancel_btn)
        
        progress_dialog.show()
        self.statusBar().showMessage(f"正在删除模型: {model_name}...")
        
        # 创建后台线程（保存为实例属性，防止被垃圾回收）
        self.transfer_worker = FileTransferWorker(
            self.device_manager,
            'delete_model',
            model_name=model_name,
            device_ip=ip
        )
        
        self.transfer_thread = QThread()
        self.transfer_worker.moveToThread(self.transfer_thread)
        
        # 连接信号
        self.transfer_thread.started.connect(self.transfer_worker.run)
        self.transfer_worker.progress.connect(lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg))
        self.transfer_worker.finished.connect(lambda success, msg: self._on_delete_model_finished(success, msg, progress_dialog, self.transfer_thread))
        
        # 启动线程
        self.transfer_thread.start()
    
        # 创建后台线程（保存为实例属性，防止被垃圾回收）
        self.transfer_worker = FileTransferWorker(
            self.device_manager,
            'delete_model',
            model_name=model_name,
            device_ip=ip
        )
        
        self.transfer_thread = QThread()
        self.transfer_worker.moveToThread(self.transfer_thread)
        
        # 连接信号
        self.transfer_thread.started.connect(self.transfer_worker.run)
        self.transfer_worker.progress.connect(lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg))
        self.transfer_worker.finished.connect(lambda success, msg: self._on_delete_model_finished(success, msg, progress_dialog, self.transfer_thread))
        
        # 启动线程
        self.transfer_thread.start()
    
    def _on_delete_model_finished(self, success, msg, progress_dialog, thread):
        """删除模型完成回调"""
        progress_dialog.close()
        thread.quit()
        thread.wait()
        
        # 清理线程资源
        self.transfer_worker = None
        self.transfer_thread = None
        
        if success:
            log_manager.info(f"[DEVICE] 模型删除成功: {msg}")
            QMessageBox.information(self, "成功", f"模型已删除！\n{msg}")
            self.statusBar().showMessage("模型删除成功", 3000)
            
            # 自动刷新模型列表
            self.refresh_model_list()
        else:
            log_manager.error(f"[DEVICE] 模型删除失败: {msg}")
            QMessageBox.critical(self, "失败", f"模型删除失败：\n{msg}")
            self.statusBar().showMessage("模型删除失败", 3000)

    def silent_check_disk_and_models(self):
        """静默检查磁盘空间和模型列表（启动时自动执行）"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            log_manager.debug("[DISK] 设备未连接，跳过磁盘空间检查")
            return
        
        ip = self.current_device_ip
        
        try:
            log_manager.info(f"[DISK] 启动时静默检查设备 {ip} 的磁盘空间...")
            
            # 检查 /oem 分区空间
            disk_info = self.device_manager.check_disk_space(ip, '/oem')
            
            if disk_info.get('success'):
                # 获取模型大小信息
                models_info = self.device_manager.get_model_sizes(ip)
                
                # 构建显示信息
                info_text = f"<b>📊 /oem 分区使用情况:</b><br><br>"
                
                if 'filesystem' in disk_info:
                    use_percent = int(disk_info['use_percent'].rstrip('%'))
                    color = 'red' if use_percent > 90 else 'orange' if use_percent > 80 else 'green'
                    
                    info_text += f"文件系统: {disk_info['filesystem']}<br>"
                    info_text += f"总容量: <b>{disk_info['size']}</b><br>"
                    info_text += f"已使用: <b style='color: orange;'>{disk_info['used']}</b><br>"
                    info_text += f"可用空间: <b style='color: green;'>{disk_info['available']}</b><br>"
                    info_text += f"使用率: <b style='color: {color};'>{disk_info['use_percent']}</b><br><br>"
                
                # 显示模型列表
                if models_info.get('success') and models_info.get('models'):
                    info_text += "<b>📦 当前模型文件 ({count}个):</b><br>".format(count=len(models_info['models']))
                    for model in models_info['models']:
                        info_text += f"• {model['name']} - {model['size']}<br>"
                else:
                    info_text += "<i>没有找到模型文件</i>"
                
                # 更新UI显示（在主线程中执行）
                # 先检查控件是否存在，避免在标签页未创建时报错
                if hasattr(self, 'disk_info_label') and self.disk_info_label is not None:
                    QTimer.singleShot(0, lambda: self.disk_info_label.setText(info_text))
                    log_manager.debug("[DISK] UI显示已更新")
                else:
                    log_manager.debug("[DISK] disk_info_label控件尚未创建，跳过UI更新")
                
                log_manager.info(f"[DISK] 磁盘空间检查完成: {disk_info.get('use_percent', 'N/A')} 已使用, {len(models_info.get('models', []))} 个模型")
                
                # 如果空间严重不足，记录警告但不弹窗
                use_percent = int(disk_info.get('use_percent', '0%').rstrip('%'))
                if use_percent > 90:
                    log_manager.warning(f"[DISK] ⚠️ 警告: /oem分区使用率已达 {disk_info['use_percent']}，建议清理旧模型")
                
            else:
                error_msg = disk_info.get('error', '未知错误')
                log_manager.error(f"[DISK] 启动时磁盘空间检查失败: {error_msg}")
                # 静默失败，不更新UI
                
        except Exception as e:
            log_manager.error(f"[DISK] 启动时检查磁盘空间异常: {str(e)}", exc_info=True)
            # 静默失败，不影响程序正常运行

    def update_oem_usage_display(self):
        """更新oem分区占用显示（在已部署模型区域）"""
        if not self.current_device_ip:
            return
        
        ip = self.current_device_ip
        
        try:
            # 检查 /oem 分区空间
            disk_info = self.device_manager.check_disk_space(ip, '/oem')
            
            if disk_info.get('success') and 'used' in disk_info and 'available' in disk_info:
                # 解析已使用空间和可用空间（单位MB）
                used_mb = self._parse_size_to_mb(disk_info['used'])
                available_mb = self._parse_size_to_mb(disk_info['available'])
                
                if used_mb is not None and available_mb is not None:
                    total_mb = used_mb + available_mb
                    usage_percent = (used_mb / total_mb * 100) if total_mb > 0 else 0
                    
                    # 根据使用率设置颜色
                    if usage_percent > 90:
                        color = '#d32f2f'  # 红色
                        status_text = '严重不足'
                    elif usage_percent > 80:
                        color = '#f57c00'  # 橙色
                        status_text = '较紧张'
                    else:
                        color = '#388e3c'  # 绿色
                        status_text = '正常'
                    
                    # 更新显示
                    usage_text = f"💾 OEM分区: {used_mb:.1f}MB / {total_mb:.1f}MB ({usage_percent:.1f}%) - {status_text}"
                    
                    if hasattr(self, 'oem_usage_label') and self.oem_usage_label is not None:
                        self.oem_usage_label.setText(usage_text)
                        self.oem_usage_label.setStyleSheet(f"""
                            padding: 8px; 
                            background-color: #e3f2fd; 
                            border-radius: 3px;
                            color: {color};
                            font-weight: bold;
                        """)
                        
        except Exception as e:
            log_manager.error(f"[DISK] 更新OEM占用显示失败: {str(e)}")

    def _parse_size_to_mb(self, size_str):
        """将大小字符串转换为MB数值"""
        try:
            size_str = size_str.strip().upper()
            if 'M' in size_str:
                return float(size_str.replace('M', ''))
            elif 'G' in size_str:
                return float(size_str.replace('G', '')) * 1024
            elif 'K' in size_str:
                return float(size_str.replace('K', '')) / 1024
            else:
                return float(size_str) / (1024 * 1024)  # 假设是字节
        except:
            return None

    def _on_push_config_finished(self, success, msg, progress_dialog, thread):
        """配置文件推送完成回调"""
        progress_dialog.close()
        thread.quit()
        thread.wait()
        
        # 清理线程资源
        self.transfer_worker = None
        self.transfer_thread = None
        
        if success:
            log_manager.info(f"[DEVICE] 配置文件推送成功: {msg}")
            QMessageBox.information(
                self, 
                "成功", 
                f"模型推送成功！\n{msg}\n\n"
                f"💡 提示：请在下方'配置文件管理'区域加载并编辑配置文件，然后点击'推送到设备'"
            )
            self.statusBar().showMessage("模型推送完成", 3000)
            
            # 自动刷新模型列表
            self.refresh_model_list()
        else:
            log_manager.error(f"[DEVICE] 模型推送失败: {msg}")
            QMessageBox.critical(self, "失败", f"模型推送失败：\n{msg}")
            self.statusBar().showMessage("模型推送失败", 3000)

    def refresh_model_list(self):
        """刷新模型列表"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        log_manager.info(f"[OPERATION] 刷新模型列表: {ip}")
        self.statusBar().showMessage(f"正在刷新模型列表...")
        
        try:
            models = self.device_manager.list_models(ip, 'SSH')
            
            self.model_table.setRowCount(len(models))
            for i, model in enumerate(models):
                self.model_table.setItem(i, 0, QTableWidgetItem(model['name']))
                self.model_table.setItem(i, 1, QTableWidgetItem(model['size']))
                self.model_table.setItem(i, 2, QTableWidgetItem(model['mtime']))
                
                # 添加删除按钮
                delete_btn = QPushButton("🗑️ 删除")
                delete_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #e74c3c;
                        color: white;
                        padding: 5px;
                        border-radius: 3px;
                    }
                    QPushButton:hover {
                        background-color: #c0392b;
                    }
                """)
                delete_btn.clicked.connect(lambda checked, name=model['name']: self.delete_model_from_device(name))
                self.model_table.setCellWidget(i, 3, delete_btn)
            
            log_manager.info(f"[OPERATION] 刷新完成，找到 {len(models)} 个模型")
            self.statusBar().showMessage(f"刷新完成，找到 {len(models)} 个模型", 3000)
            
            # 更新oem分区占用显示
            QTimer.singleShot(100, self.update_oem_usage_display)
            
        except Exception as e:
            log_manager.error(f"刷新模型列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"刷新模型列表失败：\n{str(e)}")
            self.statusBar().showMessage("刷新失败")

    def delete_model_from_device(self, model_name):
        """检查设备磁盘空间"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        log_manager.info(f"[DISK] 开始检查设备 {ip} 的磁盘空间...")
        self.statusBar().showMessage(f"正在检查磁盘空间...")
        
        try:
            # 检查 /oem 分区空间
            disk_info = self.device_manager.check_disk_space(ip, '/oem')
            
            if disk_info.get('success'):
                # 获取模型大小信息
                models_info = self.device_manager.get_model_sizes(ip)
                
                # 构建显示信息
                info_text = f"<b>📊 /oem 分区使用情况:</b><br><br>"
                
                if 'filesystem' in disk_info:
                    info_text += f"文件系统: {disk_info['filesystem']}<br>"
                    info_text += f"总容量: <b>{disk_info['size']}</b><br>"
                    info_text += f"已使用: <b style='color: orange;'>{disk_info['used']}</b><br>"
                    info_text += f"可用空间: <b style='color: green;'>{disk_info['available']}</b><br>"
                    info_text += f"使用率: <b style='color: {'red' if int(disk_info['use_percent'].rstrip('%')) > 80 else 'orange' if int(disk_info['use_percent'].rstrip('%')) > 60 else 'green'};'>{disk_info['use_percent']}</b><br><br>"
                
                # 检查是否有空间不足警告
                use_percent = int(disk_info.get('use_percent', '0%').rstrip('%'))
                if use_percent > 90:
                    info_text += "<b style='color: red;'>⚠️ 警告: 磁盘空间严重不足！</b><br>"
                    info_text += "建议删除不需要的模型文件以释放空间。<br><br>"
                elif use_percent > 80:
                    info_text += "<b style='color: orange;'>⚠️ 注意: 磁盘空间较紧张</b><br><br>"
                
                # 显示模型列表
                if models_info.get('success') and models_info.get('models'):
                    info_text += "<b>📦 当前模型文件:</b><br>"
                    total_size = 0
                    for model in models_info['models']:
                        info_text += f"• {model['name']} - {model['size']}<br>"
                    
                    info_text += f"<br><i>共 {len(models_info['models'])} 个模型文件</i>"
                else:
                    info_text += "<i>没有找到模型文件</i>"
                
                self.disk_info_label.setText(info_text)
                log_manager.info(f"[DISK] 磁盘空间检查完成: {disk_info.get('use_percent', 'N/A')} 已使用")
                self.statusBar().showMessage(f"磁盘空间检查完成", 3000)
                
                # 如果空间不足，提示用户
                if use_percent > 90:
                    reply = QMessageBox.question(
                        self,
                        "磁盘空间不足",
                        f"/oem 分区使用率已达 {disk_info['use_percent']}，空间严重不足！\n\n"
                        f"可用空间: {disk_info['available']}\n\n"
                        f"是否打开模型管理页面删除旧模型？",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        # 切换到模型与配置标签页（已经是当前页）
                        self.refresh_model_list()
                
            else:
                error_msg = disk_info.get('error', '未知错误')
                self.disk_info_label.setText(f"❌ 检查失败: {error_msg}")
                log_manager.error(f"[DISK] 磁盘空间检查失败: {error_msg}")
                QMessageBox.critical(self, "错误", f"检查磁盘空间失败:\n{error_msg}")
                
        except Exception as e:
            log_manager.error(f"[DISK] 检查磁盘空间异常: {str(e)}", exc_info=True)
            self.disk_info_label.setText(f"❌ 检查异常: {str(e)}")
            QMessageBox.critical(self, "错误", f"检查磁盘空间时发生异常:\n{str(e)}")
            self.statusBar().showMessage("刷新失败")

    def delete_model_from_device(self, model_name):
        """从设备删除模型文件（同步执行，无弹窗）"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要从设备 {ip} 上删除模型 '{model_name}' 吗？\n\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        log_manager.info(f"[OPERATION] 准备删除模型: {model_name} from {ip}")
        self.statusBar().showMessage(f"正在删除模型: {model_name}...")
        
        try:
            # 直接调用device_manager的delete_model方法
            success, msg = self.device_manager.delete_model(model_name, ip)
            
            if success:
                log_manager.info(f"[DEVICE] 模型删除成功: {msg}")
                self.statusBar().showMessage(f"模型已删除: {model_name}", 3000)
                
                # 自动刷新模型列表
                self.refresh_model_list()
                
                # 同时更新oem分区占用显示
                QTimer.singleShot(500, self.update_oem_usage_display)
            else:
                log_manager.error(f"[DEVICE] 模型删除失败: {msg}")
                QMessageBox.critical(self, "失败", f"模型删除失败：\n{msg}")
                self.statusBar().showMessage("模型删除失败", 3000)
                
        except Exception as e:
            log_manager.error(f"[DEVICE] 删除模型异常: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"删除模型时发生异常:\n{str(e)}")
            self.statusBar().showMessage("删除失败")



    def browse_config_file(self):
        """浏览选择配置文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择配置文件", "", "JSON Files (*.json);;INI Files (*.ini)")
        if file_name:
            self.config_file_edit.setText(file_name)
            
    def load_config(self):
        """加载配置文件"""
        config_file = self.config_file_edit.text()
        if not config_file or not os.path.exists(config_file):
            QMessageBox.warning(self, "错误", "请选择有效的配置文件")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.endswith('.json'):
                    content = json.dumps(json.load(f), indent=2, ensure_ascii=False)
                else:
                    content = f.read()
            self.config_text_edit.setText(content)
            self.statusBar().showMessage("配置加载成功", 2000)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载配置失败：\n{str(e)}")
            
    def save_config_local(self):
        """保存配置到本地"""
        config_file = self.config_file_edit.text()
        if not config_file:
            file_name, _ = QFileDialog.getSaveFileName(self, "保存配置文件", "", "JSON Files (*.json);;INI Files (*.ini)")
            if file_name:
                config_file = file_name
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(self.config_text_edit.toPlainText())
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{str(e)}")
            
    def push_config_to_device(self):
        """推送配置到设备（同步执行）"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        config_content = self.config_text_edit.toPlainText()
        ip = self.current_device_ip
        
        # 先保存到临时文件
        temp_file = "temp_config.json"
        if "xbotgo_media.ini" in self.config_file_edit.text():
            temp_file = "temp_config.ini"
            
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            
            log_manager.info(f"[OPERATION] 开始推送配置文件到 {ip}")
            
            # 创建进度对话框
            progress_dialog = QDialog(self)
            progress_dialog.setWindowTitle("推送配置")
            progress_dialog.setModal(True)
            progress_dialog.setFixedSize(400, 150)
            
            progress_layout = QVBoxLayout(progress_dialog)
            
            status_label = QLabel("正在推送配置文件...")
            status_label.setStyleSheet("font-size: 12px; padding: 10px;")
            progress_layout.addWidget(status_label)
            
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_layout.addWidget(progress_bar)
            
            cancel_btn = QPushButton("取消")
            cancel_btn.setEnabled(False)
            progress_layout.addWidget(cancel_btn)
            
            progress_dialog.show()
            self.statusBar().showMessage(f"正在推送配置文件到 {ip}...")
            
            # 同步执行推送操作
            QApplication.processEvents()  # 确保UI更新
            
            # 步骤1: 推送配置文件
            progress_bar.setValue(30)
            status_label.setText("正在推送配置文件...")
            QApplication.processEvents()
            
            success, msg = self.device_manager.push_config(temp_file, ip)
            
            if success:
                progress_bar.setValue(70)
                status_label.setText("配置推送成功，正在重启进程...")
                QApplication.processEvents()
                
                # 步骤2: 重启进程
                restart_success, restart_msg = self.device_manager.restart_media_process(ip)
                
                # 清理临时文件
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                
                progress_bar.setValue(100)
                
                if restart_success:
                    log_manager.info(f"[DEVICE] 配置推送成功: {msg}")
                    QMessageBox.information(
                        self, 
                        "成功", 
                        f"配置已成功推送到 {ip}！\n{msg}\n\n✅ multi_media进程已自动重启，新配置已生效"
                    )
                    self.statusBar().showMessage("配置推送完成", 3000)
                else:
                    log_manager.warning(f"[DEVICE] 配置推送成功但进程重启失败: {restart_msg}")
                    QMessageBox.warning(
                        self, 
                        "部分成功", 
                        f"配置已推送成功！\n{msg}\n\n⚠️ 但multi_media进程重启失败: {restart_msg}\n请手动重启进程以使配置生效"
                    )
                    self.statusBar().showMessage("配置推送成功，但进程重启失败", 3000)
            else:
                # 清理临时文件
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                
                log_manager.error(f"[DEVICE] 配置推送失败: {msg}")
                QMessageBox.critical(self, "失败", f"配置推送失败：\n{msg}")
                self.statusBar().showMessage("配置推送失败", 3000)
            
            progress_dialog.close()
            
        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_file):
                os.remove(temp_file)
            
            log_manager.error(f"[OPERATION] 推送配置异常: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"推送配置失败：\n{str(e)}")
            self.statusBar().showMessage("推送配置失败")
            
    def browse_log_file(self):
        """浏览选择日志文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择日志文件", "", "Log Files (*.log);;All Files (*)")
        if file_name:
            self.log_file_edit.setText(file_name)
    
    def browse_device_log_file(self):
        """从设备浏览日志文件"""
        if not self.device_connected or not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先连接设备")
            return
        
        # 显示进度对话框
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("获取设备日志文件")
        progress_dialog.setModal(True)
        progress_dialog.setFixedWidth(400)
        
        progress_layout = QVBoxLayout(progress_dialog)
        
        status_label = QLabel("正在获取设备日志文件列表...")
        status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        progress_layout.addWidget(status_label)
        
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # 不确定进度
        progress_layout.addWidget(progress_bar)
        
        progress_dialog.show()
        
        try:


            # 连接到设备
            success, output = self.device_manager.execute_ssh_command("ls /userdata/logs/*.log")
            
            if not success or not output:
                progress_dialog.close()
                QMessageBox.warning(self, "错误", f"无法获取设备日志文件列表:\n{output}")
                return
            
            # 解析文件列表
            log_files = [f.strip() for f in output.strip().split('\n') if f.strip()]
            
            if not log_files:
                progress_dialog.close()
                QMessageBox.information(self, "提示", "设备上没有日志文件")
                return
            
            progress_dialog.close()
            
            # 显示选择对话框
            from PyQt5.QtWidgets import QListWidget
            
            dialog = QDialog(self)
            dialog.setWindowTitle("选择设备日志文件")
            dialog.setModal(True)
            dialog.setFixedWidth(500)
            dialog.setFixedHeight(400)
            
            dialog_layout = QVBoxLayout(dialog)
            
            info_label = QLabel(f"设备 /userdata/logs 目录下的日志文件（共{len(log_files)}个）:")
            info_label.setStyleSheet("font-weight: bold; padding: 5px;")
            dialog_layout.addWidget(info_label)
            
            file_list = QListWidget()
            for log_file in log_files:
                file_list.addItem(log_file)
            dialog_layout.addWidget(file_list)
            
            button_layout = QHBoxLayout()
            ok_btn = QPushButton("选择")
            cancel_btn = QPushButton("取消")
            button_layout.addWidget(ok_btn)
            button_layout.addWidget(cancel_btn)
            dialog_layout.addLayout(button_layout)
            
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            
            if dialog.exec_() == QDialog.Accepted:
                selected_items = file_list.selectedItems()
                if selected_items:
                    selected_file = selected_items[0].text()
                    self.log_file_edit.setText(selected_file)
                    QMessageBox.information(self, "成功", f"已选择: {selected_file}\n\n分析时将自动从设备下载")
                    
        except Exception as e:
            progress_dialog.close()
            QMessageBox.critical(self, "错误", f"获取设备日志文件失败:\n{str(e)}")
    
    def load_device_logs(self):
        """从设备加载日志文件列表到表格"""
        if not self.device_connected or not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先连接设备")
            return

        QApplication.processEvents()
        
        try:
            # 连接到设备，获取日志文件列表
            success, output = self.device_manager.execute_ssh_command("ls -lh /userdata/logs/*.log 2>/dev/null || echo 'NO_FILES'")
            
            if not success:
                QMessageBox.warning(self, "错误", f"无法获取设备日志文件列表:\n{output}")
                return
            
            # 清空表格
            self.device_log_table.setRowCount(0)
            
            # 检查是否有文件
            if 'NO_FILES' in output or not output.strip():
                QMessageBox.information(self, "提示", "设备上没有日志文件")
                return
            
            # 解析文件列表（格式：-rw-r--r-- 1 root root 1.2K May 19 10:30 /userdata/logs/multi_media_20240519.log）
            log_files = []
            for line in output.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    size = parts[4]
                    month = parts[5]
                    day = parts[6]
                    time_or_year = parts[7]
                    filename = parts[8]
                    
                    # 只处理 multi_media 开头的日志文件
                    if not os.path.basename(filename).startswith('multi_media'):
                        continue
                    
                    log_files.append({
                        'filename': filename,
                        'size': size,
                        'time': f"{month} {day} {time_or_year}"
                    })
            
            if not log_files:
                QMessageBox.information(self, "提示", "设备上没有 multi_media 开头的日志文件")
                return
            
            # 填充表格
            self.device_log_table.setRowCount(len(log_files))
            for i, log_info in enumerate(log_files):
                # 第0列：文件名
                filename_item = QTableWidgetItem(os.path.basename(log_info['filename']))
                filename_item.setData(Qt.UserRole, log_info['filename'])  # 存储完整路径
                self.device_log_table.setItem(i, 0, filename_item)
                
                # 第1列：大小
                self.device_log_table.setItem(i, 1, QTableWidgetItem(log_info['size']))
                
                # 第2列：修改时间
                self.device_log_table.setItem(i, 2, QTableWidgetItem(log_info['time']))
                
                # 第3列：操作按钮
                btn_widget = QWidget()
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(2, 2, 2, 2)
                
                select_btn = QPushButton("选择")
                select_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 4px 8px;")
                select_btn.clicked.connect(lambda checked, idx=i: self.select_log_from_table(idx))
                btn_layout.addWidget(select_btn)
                
                delete_btn = QPushButton("删除")
                delete_btn.setStyleSheet("background-color: #f44336; color: white; padding: 4px 8px;")
                delete_btn.clicked.connect(lambda checked, idx=i: self.delete_device_log(idx))
                btn_layout.addWidget(delete_btn)
                
                btn_layout.addStretch()
                self.device_log_table.setCellWidget(i, 3, btn_widget)
            
            log_manager.info(f"[LOG] 已加载 {len(log_files)} 个日志文件到列表")
            self.statusBar().showMessage(f"已加载 {len(log_files)} 个日志文件", 3000)
            
        except Exception as e:
            progress_dialog.close()
            log_manager.error(f"[LOG] 获取设备日志文件失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"获取设备日志文件失败:\n{str(e)}")
    
    def select_log_from_table(self, row_index):
        """从表格中选择日志文件"""
        item = self.device_log_table.item(row_index, 0)
        if item:
            full_path = item.data(Qt.UserRole)
            self.log_file_edit.setText(full_path)
            log_manager.info(f"[LOG] 已选择日志文件: {full_path}")
            QMessageBox.information(self, "成功", f"已选择: {os.path.basename(full_path)}\n\n点击'分析日志'按钮开始分析")
    
    def load_selected_log(self):
        """加载选中的日志文件"""
        selected_rows = self.device_log_table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请先选择一个日志文件")
            return
        
        # 获取第一行的文件名
        row = self.device_log_table.row(selected_rows[0])
        item = self.device_log_table.item(row, 0)
        if item:
            full_path = item.data(Qt.UserRole)
            self.log_file_edit.setText(full_path)
            log_manager.info(f"[LOG] 已加载日志文件: {full_path}")
            QMessageBox.information(self, "成功", f"已加载: {os.path.basename(full_path)}\n\n点击'分析日志'按钮开始分析")
    
    def delete_device_log(self, row_index):
        """删除设备上的日志文件"""
        item = self.device_log_table.item(row_index, 0)
        if not item:
            return
        
        full_path = item.data(Qt.UserRole)
        filename = os.path.basename(full_path)
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除设备上的日志文件吗？\n\n{filename}\n\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # 检查设备连接
            if not self.device_connected or not self.current_device_ip:
                QMessageBox.warning(self, "错误", "请先连接设备")
                return
            
            # 执行删除命令
            success, output = self.device_manager.execute_ssh_command(f"rm -f {full_path}")
            
            if success:
                log_manager.info(f"[LOG] 已删除设备日志文件: {full_path}")
                QMessageBox.information(self, "成功", f"已删除: {filename}")
                
                # 刷新日志列表
                self.load_device_logs()
            else:
                QMessageBox.critical(self, "错误", f"删除失败:\n{output}")
                
        except Exception as e:
            log_manager.error(f"[LOG] 删除设备日志文件失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"删除失败:\n{str(e)}")
    
    def toggle_monitoring(self):
        """分析日志文件"""

            
        cancel_btn = QPushButton("取消")
        cancel_btn.setEnabled(False)
        progress_layout.addWidget(cancel_btn)
        
        progress_dialog.show()
        self.statusBar().showMessage(f"正在推送配置文件到 {ip}...")
        
        # 创建后台线程
        worker = FileTransferWorker(
            self.device_manager,
            'push_config',
            config_file=temp_file,
            device_ip=ip
        )
        
        thread = QThread()
        worker.moveToThread(thread)
        
        # 连接信号
        thread.started.connect(worker.run)
        worker.progress.connect(lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg))
        worker.finished.connect(lambda success, msg: self._on_push_config_finished(success, msg, progress_dialog, thread))
        
        # 启动线程
        thread.start()
    
    def _on_push_config_finished(self, success, msg, progress_dialog, thread):
        """推送配置完成回调"""
        progress_dialog.close()
        thread.quit()
        thread.wait()
        
        # 清理线程资源
        self.transfer_worker = None
        self.transfer_thread = None
        
        if success:
            log_manager.info(f"[DEVICE] 配置推送成功: {msg}")
            QMessageBox.information(self, "成功", f"配置已推送！\n{msg}")
            self.statusBar().showMessage("配置推送成功", 3000)
        else:
            log_manager.error(f"[DEVICE] 配置推送失败: {msg}")
            QMessageBox.critical(self, "失败", f"配置推送失败：\n{msg}")
            self.statusBar().showMessage("配置推送失败", 3000)

    def _on_delete_model_finished(self, success, msg, progress_dialog, thread):
        """删除模型完成回调"""
        progress_dialog.close()
        thread.quit()
        thread.wait()
        
        # 清理线程资源
        self.transfer_worker = None
        self.transfer_thread = None
        
        if success:
            log_manager.info(f"[DEVICE] 模型删除成功: {msg}")
            QMessageBox.information(self, "成功", f"模型已删除！\n{msg}")
            self.statusBar().showMessage("模型删除成功", 3000)
            
            # 自动刷新模型列表
            self.refresh_model_list()
        else:
            log_manager.error(f"[DEVICE] 模型删除失败: {msg}")
            QMessageBox.critical(self, "失败", f"模型删除失败：\n{msg}")
            self.statusBar().showMessage("模型删除失败", 3000)

    def toggle_monitoring(self):
        """切换监控状态（开始/停止）"""
        if self.is_monitoring:
            # 当前正在监控，执行停止
            self.stop_performance_monitor_action()
        else:
            # 当前未监控，执行开始
            self.start_performance_monitor_action()
    
    def start_performance_monitor(self):
        """开始性能监控（保留兼容性）"""
        self.start_performance_monitor_action()
    
    def start_performance_monitor_action(self):
        """开始性能监控的实际操作"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        try:
            ip = self.current_device_ip
            ddr_freq = self.ddr_freq_spin.value()
            interval = self.monitor_interval_spin.value()
            
            # 检查是否已设置DDR工具路径
            if not hasattr(self.performance_monitor, 'local_tool_path') or not self.performance_monitor.local_tool_path:
                # 提示用户选择DDR测试工具文件
                reply = QMessageBox.question(
                    self,
                    "选择DDR测试工具",
                    "首次使用需要选择DDR带宽测试工具文件(rk-msch-probe-for-user-64bit-1)。\n\n"
                    "是否现在选择该工具文件？\n\n"
                    "（如果设备已有该工具，可以跳过）",
                    QMessageBox.Yes | QMessageBox.No


                )
                
                if reply == QMessageBox.Yes:
                    tool_file, _ = QFileDialog.getOpenFileName(
                        self, 
                        "选择DDR测试工具", 
                        "", 
                        "Executable Files (*);;All Files (*)"
                    )
                    
                    if tool_file:
                        success, msg = self.performance_monitor.set_tool_path(tool_file)
                        if success:
                            self.statusBar().showMessage(f"DDR工具已设置: {os.path.basename(tool_file)}", 3000)
                        else:
                            QMessageBox.warning(self, "警告", msg)
            
            # 显示进度对话框
            progress_dialog = QDialog(self)
            progress_dialog.setWindowTitle("性能监控")
            progress_dialog.setModal(True)
            progress_dialog.setFixedSize(400, 150)
            
            layout = QVBoxLayout(progress_dialog)
            
            status_label = QLabel("正在初始化性能监控...")
            status_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(status_label)
            
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            layout.addWidget(progress_bar)
            
            detail_label = QLabel("")
            detail_label.setAlignment(Qt.AlignCenter)
            detail_label.setStyleSheet("color: gray; font-size: 10px;")
            layout.addWidget(detail_label)
            
            progress_dialog.show()
            QApplication.processEvents()
            
            def update_progress(percent, message):
                """更新进度回调"""
                status_label.setText(message)
                progress_bar.setValue(percent)
                detail_label.setText(f"{percent}%")
                QApplication.processEvents()
            
            # 在后台线程中启动监控
            def start_monitor_worker():
                try:
                    update_progress(10, "正在建立SSH连接...")
                    self.performance_monitor.start_monitoring(ip, ddr_freq, interval, update_progress)
                    update_progress(100, "监控已启动！")
                    return True, "success"
                except Exception as e:
                    return False, str(e)
            
            # 使用 QTimer 延迟执行，让进度对话框先显示
            def delayed_start():
                success, msg = start_monitor_worker()
                progress_dialog.close()
                
                if success:
                    self.is_monitoring = True
                    self.monitor_btn.setText("停止监控")
                    self.monitor_btn.setStyleSheet("background-color: #f44336; color: white;")
                    self.update_timer.start(interval * 1000)
                    QMessageBox.information(
                        self, 
                        "监控已启动", 
                        f"性能监控已启动！\n\n设备IP: {ip}\n采样间隔: {interval}秒\nDDR频率: {ddr_freq} MHz"
                    )
                    self.statusBar().showMessage(f"性能监控运行中 - 采样间隔: {interval}秒", 5000)
                else:
                    QMessageBox.critical(self, "启动失败", f"性能监控启动失败：\n{msg}")
                    self.statusBar().showMessage("性能监控启动失败", 3000)
            
            QTimer.singleShot(100, delayed_start)
            
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"性能监控启动失败：\n{str(e)}")
            self.statusBar().showMessage("性能监控启动失败", 3000)
        
    def stop_performance_monitor(self):
        """停止性能监控（保留兼容性）"""
        self.stop_performance_monitor_action()
    
    def stop_performance_monitor_action(self):
        """停止性能监控的实际操作"""
        try:
            self.performance_monitor.stop_monitoring()
            self.update_timer.stop()
            
            self.is_monitoring = False
            self.monitor_btn.setText("开始监控")
            self.monitor_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            
            # 显示停止提示
            msg = "性能监控已停止！"
            QMessageBox.information(self, "监控已停止", msg)
            self.statusBar().showMessage("性能监控已停止", 3000)
            
        except Exception as e:
            QMessageBox.critical(self, "停止失败", f"性能监控停止失败：\n{str(e)}")
            self.statusBar().showMessage("性能监控停止失败", 3000)

    def update_performance_data(self):
        """更新性能数据"""
        data = self.performance_monitor.get_latest_data()
        ddr_modules = data.get('ddr_modules', {})
        
        # 更新表格 - 显示NPU各Core、CPU、内存(MB)、DDR总带宽和各模块
        self.perf_table.setRowCount(22)
        metrics = [
            ("NPU Core0占用率", f"{data.get('npu_core0', 0):.1f}%"),
            ("NPU Core1占用率", f"{data.get('npu_core1', 0):.1f}%"),
            ("NPU平均占用率", f"{data.get('npu_load', 0):.1f}%"),
            ("CPU占用率", f"{data.get('cpu_usage', 0):.1f}%"),
            ("内存使用", f"{data.get('memory_used_mb', 0):.0f} / {data.get('memory_total_mb', 0):.0f} MB"),
            ("内存占用率", f"{data.get('memory_usage', 0):.1f}%"),
            ("DDR总带宽", f"{data.get('ddr_total', 0):.2f} MB/s"),
            ("DDR-CPU", f"{ddr_modules.get('cpu', 0):.2f} MB/s"),
            ("DDR-CCI_M1", f"{ddr_modules.get('cci_m1', 0):.2f} MB/s"),
            ("DDR-CCI_M2", f"{ddr_modules.get('cci_m2', 0):.2f} MB/s"),
            ("DDR-GMAC", f"{ddr_modules.get('gmac', 0):.2f} MB/s"),
            ("DDR-ISP", f"{ddr_modules.get('isp', 0):.2f} MB/s"),
            ("DDR-VICAP", f"{ddr_modules.get('vicap', 0):.2f} MB/s"),
            ("DDR-NPU", f"{ddr_modules.get('npu', 0):.2f} MB/s"),
            ("DDR-CRYPTO", f"{ddr_modules.get('crypto', 0):.2f} MB/s"),
            ("DDR-RGA", f"{ddr_modules.get('rga', 0):.2f} MB/s"),
            ("DDR-VPSS", f"{ddr_modules.get('vpss', 0):.2f} MB/s"),
            ("DDR-GPU", f"{ddr_modules.get('gpu', 0):.2f} MB/s"),
            ("DDR-HDCP", f"{ddr_modules.get('hdcp', 0):.2f} MB/s"),
            ("DDR-VOP", f"{ddr_modules.get('vop', 0):.2f} MB/s"),
            ("DDR-UFSHC", f"{ddr_modules.get('ufshc', 0):.2f} MB/s"),
            ("DDR-Others", f"{ddr_modules.get('others', 0):.2f} MB/s"),
        ]
        
        for i, (metric, value) in enumerate(metrics):
            self.perf_table.setItem(i, 0, QTableWidgetItem(metric))
            self.perf_table.setItem(i, 1, QTableWidgetItem(value))
            
        # 更新图表
        self.update_performance_chart()
        
    def update_performance_chart(self):
        """更新性能趋势图 - 分为4个子图"""
        history = self.performance_monitor.get_history_data()
        
        self.perf_figure.clear()
        
        # 创建4个子图：2x2布局
        # 左上：NPU占用率，右上：CPU占用率
        # 左下：内存使用(MB)，右下：DDR带宽
        ax_npu = self.perf_figure.add_subplot(221)
        ax_cpu = self.perf_figure.add_subplot(222)
        ax_mem = self.perf_figure.add_subplot(223)
        ax_ddr = self.perf_figure.add_subplot(224)
        
        if history['timestamps']:
            timestamps = range(len(history['timestamps']))
            
            # 1. NPU占用率图（左上）
            ax_npu.plot(timestamps, history['npu_core0'], label='Core0', marker='o', 
                       linewidth=2, linestyle='-', color='#1f77b4')
            ax_npu.plot(timestamps, history['npu_core1'], label='Core1', marker='s', 
                       linewidth=2, linestyle='-', color='#ff7f0e')
            ax_npu.plot(timestamps, history['npu_load'], label='平均', marker='^', 
                       linewidth=2.5, linestyle='--', color='red')
            ax_npu.set_xlabel('采样点')
            ax_npu.set_ylabel('占用率 (%)')
            ax_npu.set_title('NPU占用率')
            ax_npu.legend(loc='best', fontsize=8)
            ax_npu.grid(True, alpha=0.3)
            ax_npu.set_ylim(0, 100)
            
            # 2. CPU占用率图（右上）
            ax_cpu.plot(timestamps, history['cpu_usage'], label='CPU', marker='d', 
                       linewidth=2, linestyle='-', color='#2ca02c')
            ax_cpu.set_xlabel('采样点')
            ax_cpu.set_ylabel('占用率 (%)')
            ax_cpu.set_title('CPU占用率')
            ax_cpu.legend(loc='best', fontsize=8)
            ax_cpu.grid(True, alpha=0.3)
            ax_cpu.set_ylim(0, 100)
            
            # 3. 内存使用图（左下）- 使用实际MB数
            ax_mem.plot(timestamps, history['memory_used_mb'], label='已使用', 
                       marker='v', linewidth=2, linestyle='-', color='#9467bd')
            # 添加总内存参考线
            if history['memory_total_mb']:
                total_mb = history['memory_total_mb'][-1]  # 使用最新的总内存
                ax_mem.axhline(y=total_mb, color='red', linestyle='--', 
                              linewidth=1, label=f'总内存({total_mb:.0f} MB)')
            ax_mem.set_xlabel('采样点')
            ax_mem.set_ylabel('内存 (MB)')
            ax_mem.set_title('内存使用')
            ax_mem.legend(loc='best', fontsize=8)
            ax_mem.grid(True, alpha=0.3)
            
            # 4. DDR带宽图（右下）
            if history['ddr_total']:
                # 总带宽
                ax_ddr.plot(timestamps, history['ddr_total'], label='总带宽', 
                           linewidth=2.5, color='red', marker='d')
                
                # 添加主要模块的带宽曲线
                if history['ddr_modules']:
                    modules_to_show = {
                        'isp': ('ISP', '#1f77b4', '-'),
                        'npu': ('NPU', '#ff7f0e', '-'),
                        'vicap': ('VICAP', '#2ca02c', '-'),
                        'cpu': ('CPU', '#d62728', '-'),
                        'gpu': ('GPU', '#9467bd', '-'),
                        'rga': ('RGA', '#8c564b', '-')
                    }
                    
                    for module, (label, color, style) in modules_to_show.items():
                        if module in history['ddr_modules'][0]:
                            module_data = [m.get(module, 0) for m in history['ddr_modules']]
                            ax_ddr.plot(timestamps, module_data, label=label, 
                                       linewidth=1.5, linestyle=style, color=color, alpha=0.7)
                
                ax_ddr.set_xlabel('采样点')
                ax_ddr.set_ylabel('带宽 (MB/s)')
                ax_ddr.set_title('DDR带宽监控')
                ax_ddr.legend(loc='best', fontsize=8)
                ax_ddr.grid(True, alpha=0.3)
            
        self.perf_figure.tight_layout()
        self.perf_canvas.draw()
        
    def browse_log_file(self):
        """浏览选择日志文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择日志文件", "", "Log Files (*.log);;All Files (*)")
        if file_name:
            self.log_file_edit.setText(file_name)
            
    def analyze_log(self):
        """分析日志文件"""
        log_file = self.log_file_edit.text()
        if not log_file:
            QMessageBox.warning(self, "错误", "请选择有效的日志文件")
            return
        
        self.statusBar().showMessage("正在分析日志...")
        
        try:
            # 检查是否是设备路径
            if log_file.startswith('/userdata/'):
                # 从设备下载日志文件
                if not self.device_connected or not self.current_device_ip:
                    QMessageBox.warning(self, "错误", "请先连接设备")
                    return
                
                # 显示进度对话框
                progress_dialog = QDialog(self)
                progress_dialog.setWindowTitle("下载日志文件")
                progress_dialog.setModal(True)
                progress_dialog.setFixedWidth(400)
                
                progress_layout = QVBoxLayout(progress_dialog)
                
                status_label = QLabel(f"正在从设备下载:\n{log_file}")
                status_label.setStyleSheet("font-size: 14px; padding: 10px;")
                progress_layout.addWidget(status_label)
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 0)
                progress_layout.addWidget(progress_bar)
                
                progress_dialog.show()
                QApplication.processEvents()
                
                # 下载到临时文件
                import tempfile
                temp_dir = tempfile.gettempdir()
                local_file = os.path.join(temp_dir, os.path.basename(log_file))
                
                # 使用SCP下载文件
                try:
                    self.device_manager.scp_download_file(log_file, local_file)
                    log_file = local_file
                except Exception as download_error:
                    progress_dialog.close()
                    QMessageBox.critical(self, "错误", f"下载日志文件失败:\n{str(download_error)}")
                    return
                
                progress_dialog.close()
                
            # 检查本地文件是否存在
            if not os.path.exists(log_file):
                QMessageBox.warning(self, "错误", "日志文件不存在")
                return
            
            # 使用LogAnalyzer分析
            results = self.log_analyzer.analyze(log_file)
            
            # 显示汇总结果（类似已部署模型的表格效果）
            self.result_table.setRowCount(len(results))
            for i, (model, stats) in enumerate(results.items()):
                # 第0列：模型名称
                self.result_table.setItem(i, 0, QTableWidgetItem(model))
                # 第1列：推理平均(ms)
                self.result_table.setItem(i, 1, QTableWidgetItem(f"{stats['infer_avg']:.3f}"))
                # 第2列：总耗时平均(ms)
                self.result_table.setItem(i, 2, QTableWidgetItem(f"{stats['total_avg']:.3f}"))
                # 第3列：最大耗时(ms)
                self.result_table.setItem(i, 3, QTableWidgetItem(f"{stats['total_max']:.3f}"))
                # 第4列：帧数
                self.result_table.setItem(i, 4, QTableWidgetItem(str(stats['frame_count'])))
                # 第5列：推理标准差(ms)
                self.result_table.setItem(i, 5, QTableWidgetItem(f"{stats['infer_std']:.3f}"))
                # 第6列：总耗时标准差(ms)
                self.result_table.setItem(i, 6, QTableWidgetItem(f"{stats['total_std']:.3f}"))
            
            # 绘制曲线
            self.plot_log_results(log_file)
            
            # 保存CSV
            self.log_analyzer.save_csv("frame_data.csv", "summary.csv")
            
            total_frames = sum(stats['frame_count'] for stats in results.values())
            QMessageBox.information(
                self, 
                "成功", 
                f"✅ 日志分析完成！\n\n"
                f" 共分析了 {len(results)} 个模型，总计 {total_frames} 帧\n"
                f" 已生成 frame_data.csv 和 summary.csv"
            )
            self.statusBar().showMessage(f"日志分析完成，共 {len(results)} 个模型，{total_frames} 帧", 3000)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"日志分析失败：\n{str(e)}")
            
    def plot_log_results(self, log_file):
        """绘制日志分析结果"""
        data = self.log_analyzer.parse_log(log_file)
        
        self.log_figure.clear()
        
        num_models = len(data)
        if num_models == 0:
            return
            
        fig_axes = self.log_figure.subplots(num_models, 1, sharex=True)
        if num_models == 1:
            fig_axes = [fig_axes]
        
        colors = ['#2196F3', '#4CAF50', '#FF9800', '#f44336']
        
        for idx, (model, model_data) in enumerate(data.items()):
            ax = fig_axes[idx]
            length = min(len(model_data['infer']), len(model_data['total']))
            frames = range(1, length + 1)
            
            ax.plot(frames, model_data['total'][:length], label='Total', color=colors[idx % len(colors)])
            ax.plot(frames, model_data['infer'][:length], label='Infer', linestyle='--', color=colors[idx % len(colors)])
            ax.set_ylabel('Time (ms)')
            ax.set_title(model)
            ax.legend(loc='upper right')
            ax.grid(True)
            
        fig_axes[-1].set_xlabel('Frame')
        
        # 使用tight_layout并捕获警告，避免布局问题
        try:
            self.log_figure.tight_layout()
        except Exception:
            # 如果tight_layout失败，使用bbox_inches='tight'作为备选
            pass
        
        self.log_canvas.draw()
        
    def export_csv(self):
        """导出CSV文件"""
        if hasattr(self.log_analyzer, 'data') and self.log_analyzer.data:
            self.log_analyzer.save_csv("frame_data.csv", "summary.csv")
            QMessageBox.information(self, "成功", "CSV文件已导出到当前目录")
        else:
            QMessageBox.warning(self, "警告", "请先分析日志文件")
            
    def export_log_plot(self):
        """导出耗时曲线图 - 每个RKNN模型一张独立图片"""
        if not hasattr(self.log_analyzer, 'data') or not self.log_analyzer.data:
            QMessageBox.warning(self, "警告", "请先分析日志文件")
            return
        
        # 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(
            self, 
            "选择保存图片的目录"
        )
        
        if not save_dir:
            return
        
        try:
            import os
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
            
            exported_files = []
            
            # 为每个模型生成独立的图表
            for model_name, model_data in self.log_analyzer.data.items():
                if not model_data['infer'] or not model_data['total']:
                    continue
                
                # 创建独立的图表
                fig = Figure(figsize=(10, 6))
                canvas = FigureCanvas(fig)
                ax = fig.add_subplot(111)
                
                length = min(len(model_data['infer']), len(model_data['total']))
                frames = range(1, length + 1)
                
                # 绘制数据
                ax.plot(frames, model_data['total'][:length], label='Total', color='#2196F3', linewidth=2)
                ax.plot(frames, model_data['infer'][:length], label='Infer', linestyle='--', color='#FF9800', linewidth=2)
                
                # 设置标签和标题
                ax.set_xlabel('Frame', fontsize=12)
                ax.set_ylabel('Time (ms)', fontsize=12)
                ax.set_title(f'{model_name} - Inference Time Analysis', fontsize=14, fontweight='bold')
                ax.legend(loc='upper right', fontsize=11)
                ax.grid(True, alpha=0.3)
                
                # 添加统计信息文本框
                infer_avg = np.mean(model_data['infer'][:length])
                total_avg = np.mean(model_data['total'][:length])
                stats_text = f'Avg Infer: {infer_avg:.2f} ms\nAvg Total: {total_avg:.2f} ms\nFrames: {length}'
                ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, 
                       verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                       fontsize=9)
                
                # 保存图片
                safe_model_name = model_name.replace('.rknn', '').replace('/', '_').replace('\\', '_')
                file_path = os.path.join(save_dir, f"{safe_model_name}.png")
                fig.savefig(file_path, dpi=150, bbox_inches='tight')
                exported_files.append(file_path)
                
                # 关闭图表释放资源
                plt.close(fig)
            
            if exported_files:
                QMessageBox.information(
                    self, 
                    "成功", 
                    f"已导出 {len(exported_files)} 个模型的耗时曲线图到：\n{save_dir}\n\n" + 
                    "\n".join([os.path.basename(f) for f in exported_files[:5]]) +
                    ("\n..." if len(exported_files) > 5 else "")
                )
            else:
                QMessageBox.warning(self, "警告", "没有可导出的数据")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败：\n{str(e)}")
            
    def connect_rtsp(self):
        """连接RTSP流"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        streams = []
        if self.rtsp_channel1.isChecked():
            streams.append(f"rtsp://{ip}/live/0")
        if self.rtsp_channel2.isChecked():
            streams.append(f"rtsp://{ip}/live/1")
            
        if not streams:
            QMessageBox.warning(self, "警告", "请至少选择一个RTSP通道")
            return
            
        self.video_manager.connect_rtsp(streams)
        QMessageBox.information(self, "成功", f"已连接RTSP流:\n" + "\n".join(streams))
        
    def browse_video_file(self):
        """浏览选择视频文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi *.mov)")
        if file_name:
            self.video_file_edit.setText(file_name)
            
    def upload_video_to_device(self):
        """上传视频到设备"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        video_file = self.video_file_edit.text()
        if not video_file or not os.path.exists(video_file):
            QMessageBox.warning(self, "错误", "请选择有效的视频文件")
            return
        
        ip = self.current_device_ip
        
        reply = QMessageBox.question(self, "确认", 
                                    f"确定要上传视频 {os.path.basename(video_file)} 到设备 /userdata 目录吗？",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        
        success, msg = self.device_manager.push_video(video_file, ip)
        if success:
            QMessageBox.information(self, "成功", f"视频上传成功！\n{msg}")
        else:
            QMessageBox.critical(self, "失败", f"视频上传失败：\n{msg}")
            
    def apply_video_source(self):
        """应用视频源设置"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        source = self.video_source_combo.currentText()
        ip = self.current_device_ip
        
        # 修改xbotgo_media.ini
        ini_path = "/oem/usr/conf/xbot_media.ini"
        if source == "本地视频(/userdata)":
            video_src = "local"
        else:
            video_src = "rtsp"
            
        success, msg = self.device_manager.update_video_source(ip, ini_path, video_src)
        if success:
            QMessageBox.information(self, "成功", f"视频源已设置为: {source}\n{msg}")
        else:
            QMessageBox.critical(self, "失败", f"设置失败：\n{msg}")
            
    def load_track_modes(self):
        """加载追踪模式（不包含停止选项，因为已有单独的停止按钮）"""
        config_file = "model_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                modes = config.get('modes', [])
                self.track_mode_combo.clear()
                # 移除"停止追踪"选项，因为已有单独的停止按钮
                for mode in modes:
                    self.track_mode_combo.addItem(f"[{mode['id']}] {mode['desc']}", mode['id'])
            except Exception as e:
                log_manager.error(f"[RTMP] {error_msg}")

    def toggle_tracking(self):
        """切换追踪状态（启动/停止）"""
        if self.is_tracking:
            # 当前正在追踪，执行停止
            self.stop_tracking_action()
        else:
            # 当前未追踪，执行启动
            self.start_tracking_action()
    
    def start_tracking_action(self):
        """启动追踪"""
        mode_id = self.track_mode_combo.currentData()
        
        if mode_id is None:
            QMessageBox.warning(self, "错误", "请选择一个追踪模式")
            return
        
        success, msg = self.mqtt_controller.publish_track_command(mode_id)
        if success:
            self.is_tracking = True
            self.track_btn.setText("停止追踪")
            self.track_btn.setStyleSheet("background-color: #f44336; color: white; padding: 10px;")
            QMessageBox.information(self, "成功", f"已启动追踪\n模式ID: {mode_id}")
        else:
            QMessageBox.critical(self, "失败", f"启动追踪失败\n{msg}")
            
    def stop_tracking_action(self):
        """停止追踪"""
        success, msg = self.mqtt_controller.publish_track_command(0)
        if success:
            self.is_tracking = False
            self.track_btn.setText("启动追踪")
            self.track_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
            QMessageBox.information(self, "成功", "已停止追踪")
        else:
            QMessageBox.critical(self, "失败", f"停止追踪失败\n{msg}")
    
    def start_tracking(self):
        """启动追踪（保留兼容性）"""
        self.start_tracking_action()
            
    def stop_tracking(self):
        """停止追踪（保留兼容性）"""
        self.stop_tracking_action()

    def restart_media_process(self):
        """重启multi_media进程"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        reply = QMessageBox.question(self, "确认", 
                                    f"确定要重启设备 {ip} 上的multi_media进程吗？",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        
        success, msg = self.device_manager.restart_media_process(ip)
        if success:
            QMessageBox.information(self, "成功", f"multi_media进程已重启\n{msg}")
        else:
            QMessageBox.critical(self, "失败", f"重启失败\n{msg}")
            
    def kill_media_process(self):
        """停止multi_media进程"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        reply = QMessageBox.question(self, "确认", 
                                    f"确定要停止设备 {ip} 上的multi_media进程吗？",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        
        success, msg = self.device_manager.kill_media_process(ip)
        if success:
            QMessageBox.information(self, "成功", f"multi_media进程已停止\n{msg}")
        else:
            QMessageBox.critical(self, "失败", f"停止失败\n{msg}")
            
    def export_report(self):
        """导出综合报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"report_{timestamp}.txt"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("算法验证平台 - 测试报告\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # 性能数据
                f.write("-" * 60 + "\n")
                f.write("性能监控数据\n")
                f.write("-" * 60 + "\n")
                history = self.performance_monitor.get_history_data()
                if history['timestamps']:
                    for i, ts in enumerate(history['timestamps']):
                        f.write(f"[{ts}] NPU: {history['npu_load'][i]:.1f}% | ")
                        f.write(f"CPU: {history['cpu_usage'][i]:.1f}% | ")
                        f.write(f"MEM: {history['memory_usage'][i]:.1f}%\n")
                f.write("\n")
                
                # 日志分析数据
                f.write("-" * 60 + "\n")
                f.write("日志分析数据\n")
                f.write("-" * 60 + "\n")
                if hasattr(self.log_analyzer, 'data') and self.log_analyzer.data:
                    for model, stats in self.log_analyzer.data.items():
                        f.write(f"模型: {model}\n")
                        f.write(f"  推理平均: {stats['infer_avg']:.3f} ms\n")
                        f.write(f"  总耗时平均: {stats['total_avg']:.3f} ms\n")
                        f.write(f"  最大耗时: {stats['total_max']:.3f} ms\n\n")
                        
            QMessageBox.information(self, "成功", f"报告已导出到: {report_file}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出报告失败：\n{str(e)}")
            
    def auto_connect_device(self):
        """启动时自动加载并连接上次配置的设备（三级自动连接）"""
        try:
            if not os.path.exists(self.device_config_file):
                log_manager.info("[AUTO] 未找到设备配置文件，跳过自动连接")
                return
            
            # 加载配置
            with open(self.device_config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            device_ip = config.get('device_ip')
            rtsp_0 = config.get('rtsp_0')
            rtsp_1 = config.get('rtsp_1')
            wifi_ssid = config.get('wifi_ssid', '')
            wifi_password = config.get('wifi_password', '')
            
            if not device_ip:
                log_manager.warning("[AUTO] 配置文件中没有设备IP")
                return
            
            log_manager.info(f"[AUTO] 检测到上次配置的设备: {device_ip}，开始自动连接流程...")
            self.statusBar().showMessage(f"正在自动连接设备: {device_ip}...", 5000)
            
            # 第一级：尝试直接SSH连接
            log_manager.info("[AUTO] 第一级：尝试SSH直连...")
            test_success, test_msg = self.device_manager.connect_ssh(device_ip)
            
            if test_success:
                # SSH直连成功
                log_manager.info(f"[AUTO] SSH直连成功: {test_msg}")
                self._on_auto_connect_success(device_ip, rtsp_0, rtsp_1, "SSH直连成功")
                return
            
            # SSH连接失败（正常流程，进入第二级）
            log_manager.info(f"[AUTO] SSH直连失败: {test_msg}，尝试第二级WiFi重连...")
            
            # 第二级：检查是否有WiFi信息，尝试ADB+WiFi自动重连
            if wifi_ssid and wifi_password:
                log_manager.info("[AUTO] 第二级：检测到WiFi信息，尝试ADB+WiFi自动重连...")
                self.statusBar().showMessage("正在通过WiFi重新连接设备...", 5000)
                
                # 在后台线程中执行WiFi重连
                self._wifi_reconnect_attempt(device_ip, wifi_ssid, wifi_password, rtsp_0, rtsp_1)
                return
            
            # 第三级：没有WiFi信息或WiFi重连失败，提示用户一键配置
            log_manager.info("[AUTO] 第三级：无法自动连接，提示用户一键配置")
            self.statusBar().showMessage("自动连接失败，请使用'一键配置设备'", 3000)
            
            # 弹出对话框询问是否清除配置
            reply = QMessageBox.question(
                self,
                "连接失败",
                f"无法自动连接到上次配置的设备 ({device_ip})\n\n"
                f"错误信息: {test_msg}\n\n"
                f"请选择：\n"
                f"• 是 - 清除旧配置，打开一键配置向导\n"
                f"• 否 - 保留配置，稍后手动重试",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if os.path.exists(self.device_config_file):
                    os.remove(self.device_config_file)
                    log_manager.info("[AUTO] 已清除无效的设备配置")
                
                # 自动打开一键配置对话框
                QTimer.singleShot(500, self.open_device_setup)
                
        except Exception as e:
            log_manager.error(f"[AUTO] 自动连接异常: {str(e)}", exc_info=True)
    
    def _wifi_reconnect_attempt(self, device_ip, wifi_ssid, wifi_password, rtsp_0, rtsp_1):
        """WiFi自动重连尝试（后台线程）"""
        def reconnect_in_thread():
            try:
                log_manager.info(f"[AUTO] 正在通过ADB配置WiFi: {wifi_ssid}")
                
                # 使用SmartDeviceManager执行WiFi重连
                smart_manager = SmartDeviceManager()
                success, msg, ip, new_rtsp_0, new_rtsp_1 = smart_manager.full_auto_setup(
                    wifi_ssid, wifi_password
                )
                
                if success and ip:
                    log_manager.info(f"[AUTO] WiFi重连成功: {ip}")
                    
                    # 建立SSH连接到新获取的IP
                    log_manager.info(f"[AUTO] 正在建立SSH连接到 {ip}...")
                    ssh_success, ssh_msg = self.device_manager.connect_ssh(ip)
                    
                    if ssh_success:
                        log_manager.info(f"[AUTO] SSH连接成功: {ssh_msg}")
                        # 在主线程中更新UI
                        QTimer.singleShot(0, partial(
                            self._on_auto_connect_success,
                            ip, new_rtsp_0 or rtsp_0, new_rtsp_1 or rtsp_1,
                            "WiFi重连成功"
                        ))
                    else:
                        log_manager.error(f"[AUTO] SSH连接失败: {ssh_msg}")
                        # 在主线程中显示提示
                        QTimer.singleShot(0, partial(
                            self._on_auto_connect_failed,
                            ip, f"WiFi重连成功但SSH连接失败: {ssh_msg}"
                        ))
                else:
                    log_manager.warning(f"[AUTO] WiFi重连失败: {msg}")
                    # 在主线程中显示提示
                    QTimer.singleShot(0, partial(
                        self._on_auto_connect_failed,
                        device_ip, f"WiFi重连失败: {msg}"
                    ))
                    
            except Exception as e:
                log_manager.error(f"[AUTO] WiFi重连异常: {str(e)}")
                QTimer.singleShot(0, partial(
                    self._on_auto_connect_failed,
                    device_ip, str(e)
                ))
        
        # 启动后台线程
        thread = threading.Thread(target=reconnect_in_thread)
        thread.daemon = True
        thread.start()

    def _on_auto_connect_failed(self, device_ip, error_msg):
        """自动连接失败处理"""
        self.statusBar().showMessage("自动连接失败", 3000)
        
        reply = QMessageBox.question(
            self,
            "连接失败",
            f"无法自动连接到设备 ({device_ip})\n\n"
            f"错误信息: {error_msg}\n\n"
            f"请选择：\n"
            f"• 是 - 清除旧配置，打开一键配置向导\n"
            f"• 否 - 保留配置，稍后手动重试",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if os.path.exists(self.device_config_file):
                os.remove(self.device_config_file)
                log_manager.info("[AUTO] 已清除无效的设备配置")
            
            QTimer.singleShot(500, self.open_device_setup)
    
    def _on_auto_connect_success(self, device_ip, rtsp_0, rtsp_1, success_msg):
        """自动连接成功处理"""
        log_manager.info(f"[AUTO] {success_msg}")
        
        # 更新状态
        self.current_device_ip = device_ip
        self.device_connected = True
        self.ssh_available = True
        
        # 更新UI显示
        self.status_label.setText(f"✅ {device_ip} (自动连接)")
        self.status_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
        
        # 更新RTSP显示
        if rtsp_0 and rtsp_1:
            self.rtsp_label_0.setText(f"RTSP 0: {rtsp_0}")
            self.rtsp_label_1.setText(f"RTSP 1: {rtsp_1}")
        
        # 更新视频源管理页面的设备IP显示
        self.rtsp_device_ip_label.setText(device_ip)
        self.rtsp_device_ip_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
        
        # 自动连接MQTT
        log_manager.info(f"[AUTO] 正在自动连接MQTT Broker: {device_ip}:1883")
        self._auto_connect_mqtt(device_ip)
        
        # 关闭SSH测试连接（后续操作会重新建立）
        self.device_manager.close_ssh()
        
        log_manager.info(f"[AUTO] 设备自动连接成功！")
        self.statusBar().showMessage(f"已自动连接到设备: {device_ip}", 3000)
        
        # 显示提示
        QMessageBox.information(
            self,
            "自动连接成功",
            f"✅ 已成功连接到上次配置的设备\n\n"
            f"连接方式: {success_msg}\n"
            f"设备IP: {device_ip}\n"
            f"RTSP 0: {rtsp_0 or 'N/A'}\n"
            f"RTSP 1: {rtsp_1 or 'N/A'}\n\n"
            f"您现在可以直接使用所有功能了。"
        )
        
        # 延迟1秒后自动加载设备日志列表（让UI先完成渲染）
        QTimer.singleShot(1000, self.load_device_logs)
        self.refresh_model_list()
    
    def save_device_config(self, device_ip, rtsp_0, rtsp_1, wifi_ssid='', wifi_password=''):
        """保存设备配置到文件"""
        try:
            config = {
                'device_ip': device_ip,
                'wifi_ssid': wifi_ssid,
                'wifi_password': wifi_password,
                'rtsp_0': rtsp_0,
                'rtsp_1': rtsp_1,
                'last_connected': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(self.device_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            log_manager.info(f"[CONFIG] 设备配置已保存: {device_ip}")
            
        except Exception as e:
            log_manager.error(f"[CONFIG] 保存设备配置失败: {str(e)}")
    
    def clear_device_config(self):
        """清除保存的设备配置"""
        if not os.path.exists(self.device_config_file):
            QMessageBox.information(self, "提示", "当前没有保存的设备配置")
            return
        
        reply = QMessageBox.question(
            self,
            "确认清除",
            "确定要清除保存的设备配置吗？\n\n"
            "清除后，下次启动时需要重新使用'一键配置设备'进行配置。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(self.device_config_file)
                log_manager.info("[CONFIG] 设备配置已清除")
                
                # 重置连接状态
                self.current_device_ip = None
                self.device_connected = False
                self.ssh_available = False
                
                # 更新UI
                self.status_label.setText("未连接设备")
                self.status_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")
                self.rtsp_label_0.setText("RTSP 0: N/A")
                self.rtsp_label_1.setText("RTSP 1: N/A")
                
                QMessageBox.information(self, "成功", "设备配置已清除")
                
            except Exception as e:
                log_manager.error(f"[CONFIG] 清除配置失败: {str(e)}")
                QMessageBox.critical(self, "错误", f"清除配置失败：\n{str(e)}")

    def show_about(self):
        """显示关于信息"""
        QMessageBox.about(self, "关于", 
                         "算法验证上位机平台 v1.0\n\n"
                         "功能特性:\n"
                         "• 模型管理与推送\n"
                         "• 参数配置编辑\n"
                         "• 性能实时监控\n"
                         "• 日志分析可视化\n"
                         "• 视频源管理\n"
                         "• MQTT算法控制\n"
                         "• RTMP直播推流\n"
                         "• 一键设备配置\n\n"
                         "© 2024 Algorithm Validation Team")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    
    window = AlgorithmValidationPlatform()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
