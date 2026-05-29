# -*- coding: utf-8 -*-
"""
算法验证上位机主程序
功能:模型管理、参数配置、性能监控、日志分析、视频源管理
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QGroupBox, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QProgressBar, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox, QDoubleSpinBox,
    QRadioButton, QButtonGroup, QDialog, QDialogButtonBox, QStatusBar,
    QMenuBar, QAction, QToolBar, QInputDialog, QFrame, QAbstractItemView
)

from PyQt5.QtCore import Qt, QTimer, QThread

from PyQt5.QtGui import QFont
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 配置matplotlib支持中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
import json
import numpy as np
from datetime import datetime

# 导入自定义模块
from log_manager import LogManager
from device_manager import DeviceManager
from performance_monitor import PerformanceMonitor
from log_analyzer import LogAnalyzer
from video_manager import VideoManager
from mqtt_controller import MQTTController
from wifi_manager import WiFiManager
from device_setup_dialog import DeviceSetupDialog
from rtmp_manager import RTMPManager
from wifi_perf_test import WiFiPerfTester
from ui_components import (
    LogAnalysisTab,
    ModelConfigTab,
    PerformanceTab,
    RTMPTab,
    VideoTab,
    WiFiPerfTab,
)
from workers import (
    AutoConnectWorker,
    FileTransferWorker,
    LogDownloadWorker,
    PerformanceStartWorker,
    VideoUploadWorker,
    WiFiPerfTestWorker,
    WiFiReconnectWorker,
)

# 获取全局日志管理器
log_manager = LogManager()


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
        self.wifi_perf_tester = WiFiPerfTester()
        
        # 设备连接状态
        self.device_connected = False
        self.ssh_available = False
        self.adb_available = False
        self.current_device_ip = None
        
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
                
                # 加载追踪模式
                self.load_track_modes()

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

    def _transfer_in_progress(self):
        """检查是否已有文件传输任务正在运行。"""
        thread = getattr(self, "transfer_thread", None)
        return bool(thread and thread.isRunning())
        
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
        tab_widget.addTab(self.create_wifi_perf_tab(), "WiFi性能测试")  # 新增WiFi性能测试
        # 移除独立的"算法控制"标签页，已合并到性能监控页面

    def create_model_config_tab(self):
        """创建模型与配置合并标签页"""
        return ModelConfigTab.create_tab(self)

        
        
    def create_performance_tab(self):
        """创建性能监控标签页（包含算法控制和进程控制）"""
        return PerformanceTab.create_tab(self)

        
    def create_log_analysis_tab(self):
        """创建日志分析标签页"""
        return LogAnalysisTab.create_tab(self)

        
    def create_video_tab(self):
        """创建视频源管理标签页"""
        return VideoTab.create_tab(self)

        
    def create_rtmp_tab(self):
        """创建RTMP直播标签页"""
        return RTMPTab.create_tab(self)

        
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
            error_msg = f"RTMP推流异常: {str(e)}"
            log_manager.error(f"[RTMP] {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)
            self.rtmp_status_label.setText("❌ RTMP推流状态: 异常")
            self.statusBar().showMessage("RTMP推流异常", 3000)

    def stop_rtmp_streaming(self):
        """停止RTMP推流"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        log_manager.info("[OPERATION] 停止RTMP推流")
        
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

    def create_wifi_perf_tab(self):
        """创建WiFi性能测试标签页"""
        return WiFiPerfTab.create_tab(self)


    
    # ==================== WiFi性能测试相关函数 ====================
    
    def on_test_mode_changed(self, index):
        """测试模式切换"""
        if index == 0:  # 单点测试
            self.single_config_widget.setVisible(True)
            self.multi_config_widget.setVisible(False)
        else:  # 多点扫描
            self.single_config_widget.setVisible(False)
            self.multi_config_widget.setVisible(True)
    
    def refresh_wifi_info(self):
        """刷新WiFi信息"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        
        self.wifi_device_ip_label.setText(self.current_device_ip)
        self.wifi_device_ip_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
        
        # 获取WiFi信息
        self.wifi_perf_tester.set_device_ip(self.current_device_ip)
        wifi_info = self.wifi_perf_tester.get_wifi_info()
        
        rssi = wifi_info.get('rssi')
        speed = wifi_info.get('link_speed')
        
        rssi_text = "N/A" if rssi is None else f"{rssi:.0f} dBm"
        speed_text = "N/A" if speed is None else f"{speed:.1f} Mbps"

        self.wifi_rssi_label.setText(rssi_text)
        self.wifi_speed_label.setText(speed_text)
        
        # 根据RSSI设置颜色
        if rssi is None:
            color = "#7f8c8d"  # 灰色 - 未获取到
        elif rssi < -70:
            color = "#e74c3c"  # 红色 - 信号弱
        elif rssi < -50:
            color = "#f39c12"  # 橙色 - 信号中等
        else:
            color = "#27ae60"  # 绿色 - 信号强
        
        self.wifi_rssi_label.setStyleSheet(f"color: {color}; font-weight: bold; padding: 5px; font-size: 14px;")
        
        if wifi_info.get("valid"):
            self.statusBar().showMessage("WiFi信息已刷新", 3000)
        else:
            self.statusBar().showMessage("未读取到有效WiFi信息，请检查SSH和无线接口", 5000)

        log_manager.info(
            f"WiFi信息: RSSI={rssi_text}, 速率={speed_text}, "
            f"iface={wifi_info.get('interface')}, source={wifi_info.get('source')}"
        )
    
    def start_wifi_perf_test(self):
        """开始WiFi性能测试"""
        if not self.current_device_ip:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        
        # 更新设备IP
        self.wifi_perf_tester.set_device_ip(self.current_device_ip)
        
        test_mode = self.bandwidth_combo.currentIndex()
        duration = self.test_duration_spin.value()
        
        if test_mode == 0:  # 单点测试
            bandwidth = self.single_bandwidth_spin.value()
            self._start_single_test(bandwidth, duration)
        else:  # 多点扫描
            start_bw = self.multi_bw_start_spin.value()
            end_bw = self.multi_bw_end_spin.value()
            step_bw = self.multi_bw_step_spin.value()
            
            if start_bw >= end_bw:
                QMessageBox.warning(self, "错误", "起始带宽必须小于结束带宽")
                return
            
            bandwidths = list(range(start_bw, end_bw + 1, step_bw))
            self._start_multi_test(bandwidths, duration)
    
    def _start_single_test(self, bandwidth, duration):
        """开始单点测试"""
        self._start_wifi_test_worker("single", duration, bandwidth=bandwidth)
    
    def _start_multi_test(self, bandwidths, duration):
        """开始多点扫描测试"""
        self._start_wifi_test_worker("multi", duration, bandwidths=bandwidths)

    def _start_wifi_test_worker(self, mode, duration, bandwidth=None, bandwidths=None):
        """启动 WiFi 测试 QThread，所有 UI 更新由信号回到主线程处理。"""
        if getattr(self, "wifi_test_thread", None) and self.wifi_test_thread.isRunning():
            QMessageBox.information(self, "提示", "当前已有WiFi测试正在运行")
            return

        self.current_wifi_plot_mode = mode
        self.start_test_btn.setEnabled(False)
        self.stop_test_btn.setEnabled(True)
        self.wifi_test_status_label.setText("🔄 测试状态: 正在启动iperf3服务器...")
        self.wifi_test_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #fff3cd; 
            border-radius: 5px;
            color: #856404;
            font-size: 14px;
        """)

        self.wifi_test_thread = QThread()
        self.wifi_test_worker = WiFiPerfTestWorker(
            self.wifi_perf_tester,
            mode=mode,
            duration=duration,
            bandwidth=bandwidth,
            bandwidths=bandwidths,
        )
        self.wifi_test_worker.moveToThread(self.wifi_test_thread)

        self.wifi_test_thread.started.connect(self.wifi_test_worker.run)
        self.wifi_test_worker.progress.connect(self._on_wifi_worker_progress, Qt.QueuedConnection)
        self.wifi_test_worker.result_ready.connect(self._on_wifi_result_ready, Qt.QueuedConnection)
        self.wifi_test_worker.finished.connect(self._on_wifi_worker_finished, Qt.QueuedConnection)
        self.wifi_test_worker.finished.connect(self.wifi_test_thread.quit)
        self.wifi_test_worker.finished.connect(self.wifi_test_worker.deleteLater)
        self.wifi_test_thread.finished.connect(self.wifi_test_thread.deleteLater)
        self.wifi_test_thread.finished.connect(self._clear_wifi_worker_refs)
        self.wifi_test_thread.start()

    def _on_wifi_worker_progress(self, progress, message):
        """WiFi 测试进度更新。"""
        self.wifi_test_progress.setValue(progress)
        self.wifi_test_status_label.setText(f"🔄 {message}")

    def _on_wifi_result_ready(self, result):
        """WiFi 测试结果更新。"""
        self._add_result_to_table(result)
        self._update_wifi_chart()

    def _on_wifi_worker_finished(self, success, message):
        """WiFi 测试结束。"""
        self._update_test_status(success, message)
        if success:
            self.wifi_test_progress.setValue(100)
        self.start_test_btn.setEnabled(True)
        self.stop_test_btn.setEnabled(False)

    def _clear_wifi_worker_refs(self):
        """释放 WiFi 测试线程引用。"""
        self.wifi_test_worker = None
        self.wifi_test_thread = None
    
    def _add_result_to_table(self, result):
        """添加结果到表格"""
        row = self.wifi_result_table.rowCount()
        self.wifi_result_table.insertRow(row)

        def fmt_optional(value, suffix="", precision=1):
            if value is None:
                return "N/A"
            try:
                return f"{float(value):.{precision}f}{suffix}"
            except (TypeError, ValueError):
                return str(value)
        
        self.wifi_result_table.setItem(row, 0, QTableWidgetItem(str(result['bandwidth_target'])))
        self.wifi_result_table.setItem(row, 1, QTableWidgetItem(fmt_optional(result.get('throughput_mbps'), precision=2)))
        self.wifi_result_table.setItem(row, 2, QTableWidgetItem(fmt_optional(result.get('jitter_ms'), precision=2)))
        self.wifi_result_table.setItem(row, 3, QTableWidgetItem(fmt_optional(result.get('loss_percent'), suffix="%", precision=2)))
        self.wifi_result_table.setItem(row, 4, QTableWidgetItem(fmt_optional(result.get('avg_latency_ms'), precision=2)))
        self.wifi_result_table.setItem(row, 5, QTableWidgetItem(fmt_optional(result.get('rssi_dbm'), precision=0)))
        self.wifi_result_table.setItem(row, 6, QTableWidgetItem(fmt_optional(result.get('link_speed_mbps'), precision=1)))
        self.wifi_result_table.setItem(row, 7, QTableWidgetItem(result['timestamp']))
    
    def _update_wifi_chart(self):
        """更新WiFi性能图表"""
        if not self.wifi_perf_tester.test_results:
            return
        
        self.wifi_perf_figure.clear()
        
        # 创建子图
        ax1 = self.wifi_perf_figure.add_subplot(3, 2, 1)
        ax2 = self.wifi_perf_figure.add_subplot(3, 2, 2)
        ax3 = self.wifi_perf_figure.add_subplot(3, 2, 3)
        ax4 = self.wifi_perf_figure.add_subplot(3, 2, 4)
        ax5 = self.wifi_perf_figure.add_subplot(3, 2, 5)
        ax6 = self.wifi_perf_figure.add_subplot(3, 2, 6)

        results = self.wifi_perf_tester.test_results
        plot_mode = getattr(self, "current_wifi_plot_mode", None)
        if plot_mode is None and results:
            plot_mode = results[-1].get("test_mode", "multi")

        if plot_mode == "single":
            single_results = [r for r in results if r.get("test_mode", "single") == "single"]
            result = single_results[-1] if single_results else results[-1]
            series = result.get("interval_series") or []
            if not series:
                series = [
                    {
                        "time_s": result.get("duration", 0),
                        "throughput_mbps": result.get("throughput_mbps"),
                        "jitter_ms": result.get("jitter_ms"),
                        "loss_percent": result.get("loss_percent"),
                    }
                ]

            x_values = [point.get("time_s") for point in series]
            throughputs = [point.get("throughput_mbps") for point in series]
            jitters = [point.get("jitter_ms") for point in series]
            losses = [point.get("loss_percent") for point in series]
            latencies = [result.get("avg_latency_ms") for _ in series]
            rssis = [result.get("rssi_dbm") for _ in series]
            link_speeds = [result.get("link_speed_mbps") for _ in series]
            x_label = "时间 (s)"
            title_suffix = f" - {result.get('bandwidth_target')}Mbps"
        else:
            chart_results = [r for r in results if r.get("test_mode") == "multi"]
            if not chart_results:
                chart_results = results
            x_values = [r.get('bandwidth_target') for r in chart_results]
            throughputs = [r.get('throughput_mbps') for r in chart_results]
            jitters = [r.get('jitter_ms') for r in chart_results]
            losses = [r.get('loss_percent') for r in chart_results]
            latencies = [r.get('avg_latency_ms') for r in chart_results]
            rssis = [r.get('rssi_dbm') for r in chart_results]
            link_speeds = [r.get('link_speed_mbps') for r in chart_results]
            x_label = "目标带宽 (Mbps)"
            title_suffix = ""

        # 吞吐量
        ax1.plot(x_values, throughputs, 'o-', linewidth=2, markersize=8, color='#27ae60')
        ax1.set_xlabel(x_label, fontsize=10)
        ax1.set_ylabel('实际吞吐量 (Mbps)', fontsize=10)
        ax1.set_title(f'吞吐量测试{title_suffix}', fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        
        # 抖动
        ax2.plot(x_values, jitters, 's-', linewidth=2, markersize=8, color='#e74c3c')
        ax2.set_xlabel(x_label, fontsize=10)
        ax2.set_ylabel('抖动 (ms)', fontsize=10)
        ax2.set_title('网络抖动', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        
        # 丢包率
        ax3.plot(x_values, losses, '^-', linewidth=2, markersize=8, color='#f39c12')
        ax3.set_xlabel(x_label, fontsize=10)
        ax3.set_ylabel('丢包率 (%)', fontsize=10)
        ax3.set_title('丢包率', fontsize=12, fontweight='bold')
        ax3.grid(True, alpha=0.3)
        
        # 延迟
        ax4.plot(x_values, latencies, 'D-', linewidth=2, markersize=8, color='#3498db')
        ax4.set_xlabel(x_label, fontsize=10)
        ax4.set_ylabel('平均延迟 (ms)', fontsize=10)
        ax4.set_title('通信延迟', fontsize=12, fontweight='bold')
        ax4.grid(True, alpha=0.3)

        # RSSI
        ax5.plot(x_values, rssis, 'v-', linewidth=2, markersize=8, color='#8e44ad')
        ax5.set_xlabel(x_label, fontsize=10)
        ax5.set_ylabel('RSSI (dBm)', fontsize=10)
        ax5.set_title('信号强度', fontsize=12, fontweight='bold')
        ax5.grid(True, alpha=0.3)

        # 协商速率
        ax6.plot(x_values, link_speeds, 'P-', linewidth=2, markersize=8, color='#16a085')
        ax6.set_xlabel(x_label, fontsize=10)
        ax6.set_ylabel('协商速率 (Mbps)', fontsize=10)
        ax6.set_title('协商速率', fontsize=12, fontweight='bold')
        ax6.grid(True, alpha=0.3)
        
        # 使用tight_layout并捕获警告，避免布局问题导致递归重绘
        try:
            self.wifi_perf_figure.tight_layout()
        except Exception:
            pass
        
        self.wifi_perf_canvas.draw()
    
    def _update_test_status(self, success, message):
        """更新测试状态"""
        if success:
            self.wifi_test_status_label.setText(f"✅ 测试状态: {message}")
            self.wifi_test_status_label.setStyleSheet("""
                padding: 15px; 
                background-color: #d4edda; 
                border-radius: 5px;
                color: #155724;
                font-size: 14px;
            """)
        else:
            self.wifi_test_status_label.setText(f"❌ 测试状态: {message}")
            self.wifi_test_status_label.setStyleSheet("""
                padding: 15px; 
                background-color: #f8d7da; 
                border-radius: 5px;
                color: #721c24;
                font-size: 14px;
            """)
    
    def stop_wifi_perf_test(self):
        """停止WiFi性能测试"""
        worker = getattr(self, "wifi_test_worker", None)
        if not worker:
            self._update_test_status(False, "当前没有正在运行的测试")
            return

        log_manager.info("[WIFI] 停止 WiFi 性能测试请求已发送")
        worker.cancel()
        self.wifi_test_status_label.setText("⏹️ 测试状态: 正在停止...")
        self.wifi_test_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
            font-size: 14px;
        """)
        self.stop_test_btn.setEnabled(False)
        
        log_manager.info("WiFi性能测试已请求停止")
    
    def export_wifi_perf_csv(self):
        """导出WiFi性能测试CSV"""
        if not self.wifi_perf_tester.test_results:
            QMessageBox.warning(self, "警告", "没有可导出的测试结果")
            return
        
        filepath, msg = self.wifi_perf_tester.export_to_csv()
        
        if filepath:
            QMessageBox.information(self, "成功", f"测试结果已导出到:\n{filepath}")
            log_manager.info(f"WiFi性能测试结果已导出: {filepath}")
        else:
            QMessageBox.critical(self, "错误", msg)

    def export_wifi_perf_plot(self):
        """导出WiFi性能测试曲线图"""
        if not self.wifi_perf_tester.test_results:
            QMessageBox.warning(self, "警告", "没有可导出的测试结果")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"wifi_perf_curve_{timestamp}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出WiFi性能曲线图",
            default_name,
            "PNG图片 (*.png);;JPEG图片 (*.jpg);;PDF文件 (*.pdf);;All Files (*)",
        )

        if not file_path:
            return

        try:
            if not os.path.splitext(file_path)[1]:
                file_path += ".png"
            self._update_wifi_chart()
            self.wifi_perf_figure.savefig(file_path, dpi=150, bbox_inches='tight')
            QMessageBox.information(self, "成功", f"曲线图已导出到:\n{file_path}")
            self.statusBar().showMessage(f"WiFi曲线图已导出: {os.path.basename(file_path)}", 3000)
            log_manager.info(f"[WIFI] 性能曲线图已导出: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出曲线图失败:\n{str(e)}")
            log_manager.error(f"[WIFI] 导出性能曲线图失败: {str(e)}", exc_info=True)
    
    def clear_wifi_results(self):
        """清空WiFi测试结果"""
        reply = QMessageBox.question(
            self, 
            "确认", 
            "确定要清空所有测试结果吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        self.wifi_perf_tester.clear_results()
        self.wifi_result_table.setRowCount(0)
        
        # 清空图表
        self.wifi_perf_figure.clear()
        self.wifi_perf_canvas.draw()
        
        self.wifi_test_progress.setValue(0)
        self.wifi_test_status_label.setText("⏸️ 测试状态: 就绪")
        self.wifi_test_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
            font-size: 14px;
        """)
        
        log_manager.info("WiFi测试结果已清空")
    
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

        if self._transfer_in_progress():
            QMessageBox.information(self, "提示", "已有文件传输任务正在进行，请稍后再试")
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
        cancel_btn.setEnabled(False)
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
        self.transfer_worker.progress.connect(
            lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg),
            Qt.QueuedConnection
        )
        self.transfer_worker.finished.connect(
            lambda success, msg: self._on_push_model_finished(success, msg, progress_dialog, self.transfer_thread, ip),
            Qt.QueuedConnection
        )
        
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
    
    def delete_model(self, ip, model_name):
        if self._transfer_in_progress():
            QMessageBox.information(self, "提示", "已有文件传输任务正在进行，请稍后再试")
            return

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
        self.transfer_worker.progress.connect(
            lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg),
            Qt.QueuedConnection
        )
        self.transfer_worker.finished.connect(
            lambda success, msg: self._on_delete_model_finished(success, msg, progress_dialog, self.transfer_thread),
            Qt.QueuedConnection
        )
        
        # 启动线程
        self.transfer_thread.start()
    
    def upload_video_to_device(self):
        """上传视频到设备（后台线程+进度显示）"""
        if getattr(self, "video_upload_thread", None) and self.video_upload_thread.isRunning():
            QMessageBox.information(self, "提示", "当前已有视频正在上传")
            return

        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return

        if self._transfer_in_progress():
            QMessageBox.information(self, "提示", "已有文件传输任务正在进行，请稍后再试")
            return

        video_file = self.video_file_edit.text()
        if not video_file or not os.path.exists(video_file):
            QMessageBox.warning(self, "错误", "请选择有效的视频文件")
            return
        
        ip = self.current_device_ip
        
        reply = QMessageBox.question(self, "确认", 
                                    f"确定要上传视频 {os.path.basename(video_file)} 到设备 /userdata 目录吗？\n\n"
                                    f"文件大小: {os.path.getsize(video_file) / 1024 / 1024:.2f} MB",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        
        # 创建进度对话框
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("视频上传")
        progress_dialog.setModal(True)
        progress_dialog.setFixedSize(400, 150)
        
        layout = QVBoxLayout(progress_dialog)
        
        # 状态标签
        status_label = QLabel(f"正在上传: {os.path.basename(video_file)}")
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)
        
        # 进度条
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        layout.addWidget(progress_bar)
        
        # 进度文本
        progress_text = QLabel("准备上传...")
        progress_text.setAlignment(Qt.AlignCenter)
        layout.addWidget(progress_text)
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        cancel_layout.addWidget(cancel_btn)
        layout.addLayout(cancel_layout)

        self.video_upload_thread = QThread()
        self.video_upload_worker = VideoUploadWorker(self.device_manager, video_file, ip)
        self.video_upload_worker.moveToThread(self.video_upload_thread)

        def update_progress(percent, transferred_mb, total_mb):
            progress_bar.setValue(percent)
            progress_text.setText(f"{percent}% ({transferred_mb:.2f} MB / {total_mb:.2f} MB)")
        
        def upload_finished(success, msg):
            progress_dialog.accept()

            if success:
                QMessageBox.information(self, "成功", f"视频上传成功！\n{msg}")
                log_manager.info(f"[VIDEO] 上传完成: {msg}")
            elif msg == "上传已取消":
                QMessageBox.information(self, "提示", msg)
                log_manager.info("[VIDEO] 用户取消了上传")
            else:
                QMessageBox.critical(self, "失败", f"视频上传失败：\n{msg}")
                log_manager.error(f"[VIDEO] 上传失败: {msg}")

        def cancel_upload():
            if self.video_upload_worker:
                self.video_upload_worker.cancel()
            cancel_btn.setEnabled(False)
            status_label.setText("正在取消上传...")
        
        self.video_upload_thread.started.connect(self.video_upload_worker.run)
        self.video_upload_worker.progress.connect(update_progress, Qt.QueuedConnection)
        self.video_upload_worker.finished.connect(upload_finished, Qt.QueuedConnection)
        self.video_upload_worker.finished.connect(self.video_upload_thread.quit)
        self.video_upload_worker.finished.connect(self.video_upload_worker.deleteLater)
        self.video_upload_thread.finished.connect(self.video_upload_thread.deleteLater)
        self.video_upload_thread.finished.connect(self._clear_video_upload_refs)
        cancel_btn.clicked.connect(cancel_upload)
        progress_dialog.rejected.connect(cancel_upload)

        progress_dialog.show()
        self.video_upload_thread.start()

    def _clear_video_upload_refs(self):
        """释放视频上传线程引用。"""
        self.video_upload_worker = None
        self.video_upload_thread = None


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
        """从设备删除模型文件（后台线程执行）"""
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
        self.delete_model(ip, model_name)



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
    
    def load_config_from_device(self):
        """从设备加载配置文件"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return
        
        ip = self.current_device_ip
        
        # 确定要下载的配置文件名
        current_file = self.config_file_edit.text()
        if current_file and os.path.basename(current_file):
            config_filename = os.path.basename(current_file)
        else:
            # 默认使用 model_config.json
            config_filename = "model_config.json"
        
        reply = QMessageBox.question(
            self, 
            "确认", 
            f"确定要从设备 {ip} 下载配置文件 {config_filename} 吗？\n\n这将覆盖当前编辑器中的内容。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        try:
            log_manager.info(f"[OPERATION] 开始从设备 {ip} 下载配置文件 {config_filename}")
            self.statusBar().showMessage(f"正在从设备下载 {config_filename}...")
            
            # 下载到本地（使用原文件名）
            local_file = config_filename
            success, result = self.device_manager.pull_config(config_filename, ip, local_file)
            
            if success:
                # 更新文件路径显示
                self.config_file_edit.setText(local_file)
                
                # 加载文件内容到编辑器
                with open(local_file, 'r', encoding='utf-8') as f:
                    if local_file.endswith('.json'):
                        content = json.dumps(json.load(f), indent=2, ensure_ascii=False)
                    else:
                        content = f.read()
                
                self.config_text_edit.setText(content)
                
                log_manager.info(f"[DEVICE] 配置下载成功: {result}")
                QMessageBox.information(
                    self, 
                    "成功", 
                    f"配置已从设备加载！\n\n文件: {config_filename}\n大小: {os.path.getsize(local_file)} 字节"
                )
                self.statusBar().showMessage(f"配置已从设备加载: {config_filename}", 3000)
            else:
                error_msg = result if isinstance(result, str) else "未知错误"
                log_manager.error(f"[DEVICE] 配置下载失败: {error_msg}")
                QMessageBox.critical(self, "错误", f"从设备加载配置失败：\n{error_msg}")
                
        except Exception as e:
            log_manager.error(f"[ERROR] 配置下载异常: {str(e)}")
            QMessageBox.critical(self, "错误", f"加载配置时发生错误：\n{str(e)}")
            
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
        """推送配置到设备（后台线程执行）"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            QMessageBox.warning(self, "错误", "请先通过'一键配置设备'连接设备")
            return

        if self._transfer_in_progress():
            QMessageBox.information(self, "提示", "已有文件传输任务正在进行，请稍后再试")
            return
        
        config_content = self.config_text_edit.toPlainText()
        ip = self.current_device_ip
        
        # 确定配置文件名（使用正确的文件名，确保设备能识别）
        current_file = self.config_file_edit.text()
        if current_file and os.path.basename(current_file):
            config_filename = os.path.basename(current_file)
        else:
            # 默认使用 model_config.json
            config_filename = "model_config.json"
        
        # 如果当前文件是INI格式，使用ini后缀
        if current_file and current_file.endswith('.ini'):
            config_filename = "xbotgo_media.ini"

        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_filename)
        try:
            # 保存到临时文件（使用正确的文件名）
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            
            log_manager.info(f"[OPERATION] 开始推送配置文件 {config_filename} 到 {ip}")
            
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

            self.transfer_worker = FileTransferWorker(
                self.device_manager,
                'push_config',
                config_file=temp_file,
                device_ip=ip
            )
            self.transfer_thread = QThread()
            self.transfer_worker.moveToThread(self.transfer_thread)

            self.transfer_thread.started.connect(self.transfer_worker.run)
            self.transfer_worker.progress.connect(
                lambda percent, msg: self._update_progress(progress_bar, status_label, percent, msg),
                Qt.QueuedConnection
            )
            self.transfer_worker.finished.connect(
                lambda success, msg: self._on_push_config_finished(success, msg, progress_dialog, self.transfer_thread),
                Qt.QueuedConnection
            )
            self.transfer_thread.start()

        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_file):
                os.remove(temp_file)
            
            log_manager.error(f"[OPERATION] 推送配置异常: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"推送配置失败：\n{str(e)}")
            self.statusBar().showMessage("推送配置失败")
            
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

        if getattr(self, "performance_start_thread", None) and self.performance_start_thread.isRunning():
            log_manager.info("[PERF] 性能监控正在启动中，忽略重复点击")
            self.statusBar().showMessage("性能监控正在启动中", 3000)
            return
        
        try:
            ip = self.current_device_ip
            ddr_freq = self.ddr_freq_spin.value()
            interval = self.monitor_interval_spin.value()
            
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

            def update_progress(percent, message):
                status_label.setText(message)
                progress_bar.setValue(percent)
                detail_label.setText(f"{percent}%")

            def start_finished(success, msg):
                progress_dialog.accept()

                if success:
                    self.is_monitoring = True
                    self.monitor_btn.setText("停止监控")
                    self.monitor_btn.setStyleSheet("background-color: #f44336; color: white;")
                    self.update_timer.start(interval * 1000)
                    log_manager.info(
                        f"[PERF] 性能监控已启动: ip={ip}, interval={interval}s, ddr_freq={ddr_freq}MHz"
                    )
                    self.statusBar().showMessage(f"性能监控运行中 - 采样间隔: {interval}秒", 5000)
                else:
                    QMessageBox.critical(self, "启动失败", f"性能监控启动失败：\n{msg}")
                    self.statusBar().showMessage("性能监控启动失败", 3000)

            self.performance_start_thread = QThread()
            self.performance_start_worker = PerformanceStartWorker(
                self.performance_monitor,
                ip,
                ddr_freq,
                interval,
            )
            self.performance_start_worker.moveToThread(self.performance_start_thread)
            self.performance_start_thread.started.connect(self.performance_start_worker.run)
            self.performance_start_worker.progress.connect(update_progress, Qt.QueuedConnection)
            self.performance_start_worker.finished.connect(start_finished, Qt.QueuedConnection)
            self.performance_start_worker.finished.connect(self.performance_start_thread.quit)
            self.performance_start_worker.finished.connect(self.performance_start_worker.deleteLater)
            self.performance_start_thread.finished.connect(self.performance_start_thread.deleteLater)
            self.performance_start_thread.finished.connect(self._clear_performance_start_refs)
            self.performance_start_thread.start()
            
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"性能监控启动失败：\n{str(e)}")
            self.statusBar().showMessage("性能监控启动失败", 3000)

    def _clear_performance_start_refs(self):
        """释放性能监控启动线程引用。"""
        self.performance_start_worker = None
        self.performance_start_thread = None
        
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
            log_manager.info("[PERF] 性能监控已停止")
            self.statusBar().showMessage("性能监控已停止", 3000)
            
        except Exception as e:
            QMessageBox.critical(self, "停止失败", f"性能监控停止失败：\n{str(e)}")
            self.statusBar().showMessage("性能监控停止失败", 3000)

    def update_performance_data(self):
        """更新性能数据"""
        data = self.performance_monitor.get_latest_data()
        ddr_modules = data.get('ddr_modules', {})
        ddr_status = data.get('ddr_status', '未启动')
        ddr_error = data.get('ddr_error')
        if ddr_error:
            ddr_error = str(ddr_error)
            if len(ddr_error) > 120:
                ddr_error = ddr_error[:117] + "..."
            ddr_status = f"{ddr_status}: {ddr_error}"

        # 更新表格 - 显示NPU各Core、CPU、内存(MB)、DDR状态、DDR总带宽和各模块
        metrics = [
            ("NPU Core0占用率", f"{data.get('npu_core0', 0):.1f}%"),
            ("NPU Core1占用率", f"{data.get('npu_core1', 0):.1f}%"),
            ("NPU平均占用率", f"{data.get('npu_load', 0):.1f}%"),
            ("CPU占用率", f"{data.get('cpu_usage', 0):.1f}%"),
            ("内存使用", f"{data.get('memory_used_mb', 0):.0f} / {data.get('memory_total_mb', 0):.0f} MB"),
            ("内存占用率", f"{data.get('memory_usage', 0):.1f}%"),
            ("DDR状态", ddr_status),
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
        self.perf_table.setRowCount(len(metrics))
        
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
        
    def export_performance_plot(self):
        """导出性能趋势图"""
        # 获取完整的监控历史数据（不限制100个点）
        history = self.performance_monitor.get_history_data(use_full_history=True)
        
        if not history['timestamps']:
            QMessageBox.warning(self, "警告", "暂无性能数据，请先启动监控")
            return
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "导出性能趋势图", 
            "performance_trend.png", 
            "PNG图片 (*.png);;所有文件 (*)"
        )
        
        if not file_path:
            return
        
        try:
            # 确保文件名以.png结尾
            if not file_path.lower().endswith('.png'):
                file_path += '.png'
            
            # 创建独立的图表用于导出（更高分辨率）
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
            
            fig = Figure(figsize=(16, 10))
            canvas = FigureCanvas(fig)
            
            # 创建4个子图：2x2布局
            ax_npu = fig.add_subplot(221)
            ax_cpu = fig.add_subplot(222)
            ax_mem = fig.add_subplot(223)
            ax_ddr = fig.add_subplot(224)
            
            timestamps = range(len(history['timestamps']))
            
            # 1. NPU占用率图（左上）
            ax_npu.plot(timestamps, history['npu_core0'], label='Core0', marker='o', 
                       linewidth=2, linestyle='-', color='#1f77b4')
            ax_npu.plot(timestamps, history['npu_core1'], label='Core1', marker='s', 
                       linewidth=2, linestyle='-', color='#ff7f0e')
            ax_npu.plot(timestamps, history['npu_load'], label='平均', marker='^', 
                       linewidth=2.5, linestyle='--', color='red')
            ax_npu.set_xlabel('采样点', fontsize=12)
            ax_npu.set_ylabel('占用率 (%)', fontsize=12)
            ax_npu.set_title('NPU占用率', fontsize=14, fontweight='bold')
            ax_npu.legend(loc='best', fontsize=10)
            ax_npu.grid(True, alpha=0.3)
            ax_npu.set_ylim(0, 100)
            
            # 2. CPU占用率图（右上）
            ax_cpu.plot(timestamps, history['cpu_usage'], label='CPU', marker='d', 
                       linewidth=2, linestyle='-', color='#2ca02c')
            ax_cpu.set_xlabel('采样点', fontsize=12)
            ax_cpu.set_ylabel('占用率 (%)', fontsize=12)
            ax_cpu.set_title('CPU占用率', fontsize=14, fontweight='bold')
            ax_cpu.legend(loc='best', fontsize=10)
            ax_cpu.grid(True, alpha=0.3)
            ax_cpu.set_ylim(0, 100)
            
            # 3. 内存使用图（左下）- 使用实际MB数
            ax_mem.plot(timestamps, history['memory_used_mb'], label='已使用', 
                       marker='v', linewidth=2, linestyle='-', color='#9467bd')
            ax_mem.set_xlabel('采样点', fontsize=12)
            ax_mem.set_ylabel('内存 (MB)', fontsize=12)
            ax_mem.set_title('内存使用', fontsize=14, fontweight='bold')
            ax_mem.legend(loc='best', fontsize=10)
            ax_mem.grid(True, alpha=0.3)
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
                
                ax_ddr.set_xlabel('采样点', fontsize=12)
                ax_ddr.set_ylabel('带宽 (MB/s)', fontsize=12)
                ax_ddr.set_title('DDR带宽监控', fontsize=14, fontweight='bold')
                ax_ddr.legend(loc='best', fontsize=10)
                ax_ddr.grid(True, alpha=0.3)
            
            # 添加总体标题
            fig.suptitle('性能监控趋势图', fontsize=16, fontweight='bold', y=0.995)
            
            # 保存图片，使用bbox_inches='tight'避免布局问题
            fig.savefig(file_path, dpi=150, bbox_inches='tight')
            
            # 关闭图表释放资源
            import matplotlib.pyplot as plt
            plt.close(fig)
            
            QMessageBox.information(self, "成功", f"性能趋势图已导出到：\n{file_path}")
            self.statusBar().showMessage(f"性能趋势图已导出: {os.path.basename(file_path)}", 3000)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败：\n{str(e)}")
            log_manager.error(f"[PERF] 导出性能趋势图失败: {str(e)}", exc_info=True)
        
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
                if not self.device_connected or not self.current_device_ip:
                    QMessageBox.warning(self, "错误", "请先连接设备")
                    return
                self._download_log_for_analysis(log_file)
                return
                
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

    def _download_log_for_analysis(self, remote_log_file):
        """后台下载设备日志，完成后继续分析。"""
        if getattr(self, "log_download_thread", None) and self.log_download_thread.isRunning():
            QMessageBox.information(self, "提示", "日志正在下载中，请稍后再试")
            return

        import tempfile

        temp_dir = os.path.join(tempfile.gettempdir(), "algo_platform_logs")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_file = os.path.join(temp_dir, f"{timestamp}_{os.path.basename(remote_log_file)}")

        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("下载日志文件")
        progress_dialog.setModal(False)
        progress_dialog.setFixedWidth(460)

        progress_layout = QVBoxLayout(progress_dialog)

        status_label = QLabel(f"正在从设备下载:\n{remote_log_file}")
        status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        status_label.setWordWrap(True)
        progress_layout.addWidget(status_label)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_layout.addWidget(progress_bar)

        speed_label = QLabel("速度: 0.00 MB/s    进度: 0.00 / 0.00 MB")
        speed_label.setStyleSheet("color: #666; padding: 4px 10px;")
        progress_layout.addWidget(speed_label)

        cancel_btn = QPushButton("取消下载")
        progress_layout.addWidget(cancel_btn)

        self.log_download_thread = QThread()
        self.log_download_worker = LogDownloadWorker(self.current_device_ip, remote_log_file, local_file)
        self.log_download_worker.moveToThread(self.log_download_thread)

        def update_progress(percent, transferred_mb, total_mb, speed_mbps):
            progress_bar.setValue(percent)
            speed_label.setText(
                f"速度: {speed_mbps:.2f} MB/s    进度: {transferred_mb:.2f} / {total_mb:.2f} MB"
            )

        def cancel_download():
            if self.log_download_worker:
                self.log_download_worker.cancel()
            cancel_btn.setEnabled(False)
            status_label.setText(f"正在取消下载并清理残留文件:\n{remote_log_file}")

        def download_finished(success, message, downloaded_file):
            progress_dialog.accept()
            if success:
                log_manager.info(f"[LOG] 日志下载完成: {downloaded_file}")
                self.log_file_edit.setText(downloaded_file)
                self.statusBar().showMessage("日志下载完成，正在分析...", 3000)
                self.analyze_log()
            elif message == "下载已取消":
                QMessageBox.information(self, "提示", "日志下载已取消，未完成文件已清理")
                self.statusBar().showMessage("日志下载已取消", 3000)
            else:
                QMessageBox.critical(self, "错误", message)
                self.statusBar().showMessage("日志下载失败", 3000)

        self.log_download_thread.started.connect(self.log_download_worker.run)
        self.log_download_worker.progress.connect(update_progress, Qt.QueuedConnection)
        self.log_download_worker.finished.connect(download_finished, Qt.QueuedConnection)
        self.log_download_worker.finished.connect(self.log_download_thread.quit)
        self.log_download_worker.finished.connect(self.log_download_worker.deleteLater)
        self.log_download_thread.finished.connect(self.log_download_thread.deleteLater)
        self.log_download_thread.finished.connect(self._clear_log_download_refs)
        cancel_btn.clicked.connect(cancel_download)
        progress_dialog.rejected.connect(cancel_download)

        progress_dialog.show()
        self.log_download_thread.start()

    def _clear_log_download_refs(self):
        """释放日志下载线程引用。"""
        self.log_download_worker = None
        self.log_download_thread = None
            
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
        file_name, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi *.mov *.h264 *.h265)")
        if file_name:
            self.video_file_edit.setText(file_name)
            
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
        """从设备加载追踪模式配置"""
        # 检查设备是否已连接
        if not self.current_device_ip:
            log_manager.warning("[CONFIG] 设备未连接，无法加载追踪模式")
            return
        
        ip = self.current_device_ip
        config_filename = "model_config.json"
        temp_file = f"temp_{config_filename}"
        
        try:
            log_manager.info(f"[CONFIG] 正在从设备 {ip} 加载追踪模式配置...")
            
            # 从设备下载配置文件到临时位置
            success, result = self.device_manager.pull_config(config_filename, ip, temp_file)
            
            if success:
                try:
                    # 读取并解析配置
                    with open(temp_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 先尝试解析，如果失败提供更详细的错误信息
                    try:
                        config = json.loads(content)
                    except json.JSONDecodeError as e:
                        # 提供更详细的错误诊断
                        error_line = e.lineno
                        error_col = e.colno
                        error_msg = str(e)
                        
                        log_manager.error(f"[CONFIG] 配置文件格式错误: {error_msg}")
                        log_manager.error(f"[CONFIG] 错误位置: 第 {error_line} 行, 第 {error_col} 列")
                        
                        # 显示错误附近的上下文
                        lines = content.split('\n')
                        if error_line <= len(lines):
                            start_line = max(0, error_line - 3)
                            end_line = min(len(lines), error_line + 2)
                            context = '\n'.join([f"{i+1}: {lines[i]}" for i in range(start_line, end_line)])
                            log_manager.error(f"[CONFIG] 错误上下文:\n{context}")
                        
                        QMessageBox.critical(
                            self, 
                            "配置文件格式错误", 
                            f"设备上的 {config_filename} 文件格式不正确：\n\n"
                            f"错误位置: 第 {error_line} 行, 第 {error_col} 列\n"
                            f"错误信息: {error_msg}\n\n"
                            f"请检查设备上的配置文件是否正确。"
                        )
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        return
                    
                    modes = config.get('modes', [])
                    self.track_mode_combo.clear()
                    
                    if modes:
                        # 移除"停止追踪"选项，因为已有单独的停止按钮
                        for mode in modes:
                            self.track_mode_combo.addItem(f"[{mode['id']}] {mode['desc']}", mode['id'])
                        
                        log_manager.info(f"[CONFIG] 成功加载 {len(modes)} 个追踪模式")
                        self.statusBar().showMessage(f"已加载 {len(modes)} 个追踪模式", 2000)
                    else:
                        log_manager.warning("[CONFIG] 配置文件中没有定义追踪模式")
                        QMessageBox.warning(self, "警告", "设备上的配置文件中没有定义追踪模式")
                    
                finally:
                    # 清理临时文件
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
            else:
                error_msg = result if isinstance(result, str) else "未知错误"
                log_manager.error(f"[CONFIG] 从设备加载配置失败: {error_msg}")
                QMessageBox.warning(
                    self, 
                    "加载失败", 
                    f"无法从设备加载追踪模式配置：\n{error_msg}\n\n请确保设备上存在 {config_filename} 文件"
                )
                
        except Exception as e:
            log_manager.error(f"[CONFIG] 加载追踪模式异常: {str(e)}")
            QMessageBox.critical(self, "错误", f"加载追踪模式时发生错误：\n{str(e)}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
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
            log_manager.info(f"[TRACK] 已启动追踪: mode_id={mode_id}")
            self.statusBar().showMessage(f"追踪已启动: 模式ID {mode_id}", 3000)
        else:
            QMessageBox.critical(self, "失败", f"启动追踪失败\n{msg}")
            
    def stop_tracking_action(self):
        """停止追踪"""
        success, msg = self.mqtt_controller.publish_track_command(0)
        if success:
            self.is_tracking = False
            self.track_btn.setText("启动追踪")
            self.track_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
            log_manager.info("[TRACK] 已停止追踪")
            self.statusBar().showMessage("追踪已停止", 3000)
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
        """启动时自动加载并连接上次配置的设备（智能IP校验+自动连接）"""
        try:
            if not os.path.exists(self.device_config_file):
                log_manager.info("[AUTO] 未找到设备配置文件，跳过自动连接")
                return
            
            # 加载配置
            with open(self.device_config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            device_ip = config.get('device_ip')
            
            if not device_ip:
                log_manager.warning("[AUTO] 配置文件中没有设备IP")
                return

            if getattr(self, "auto_connect_thread", None) and self.auto_connect_thread.isRunning():
                return

            log_manager.info(f"[AUTO] 检测到上次配置的设备: {device_ip}，启动后台连接流程...")
            self.statusBar().showMessage("正在后台检测设备状态...", 5000)

            self.auto_connect_thread = QThread()
            self.auto_connect_worker = AutoConnectWorker(self.device_manager, config)
            self.auto_connect_worker.moveToThread(self.auto_connect_thread)
            self.auto_connect_thread.started.connect(self.auto_connect_worker.run)
            self.auto_connect_worker.status.connect(
                lambda message: self.statusBar().showMessage(message, 5000),
                Qt.QueuedConnection,
            )
            self.auto_connect_worker.finished.connect(self._on_auto_connect_worker_finished, Qt.QueuedConnection)
            self.auto_connect_worker.finished.connect(self.auto_connect_thread.quit)
            self.auto_connect_worker.finished.connect(self.auto_connect_worker.deleteLater)
            self.auto_connect_thread.finished.connect(self.auto_connect_thread.deleteLater)
            self.auto_connect_thread.finished.connect(self._clear_auto_connect_refs)
            self.auto_connect_thread.start()

        except Exception as e:
            log_manager.error(f"[AUTO] 自动连接异常: {str(e)}", exc_info=True)

    def _on_auto_connect_worker_finished(self, success, device_ip, rtsp_0, rtsp_1, message):
        """启动自动连接后台任务完成。"""
        if success:
            self._on_auto_connect_success(device_ip, rtsp_0, rtsp_1, message)
        else:
            self._on_auto_connect_failed(device_ip or "未知设备", message)

    def _clear_auto_connect_refs(self):
        """释放启动自动连接线程引用。"""
        self.auto_connect_worker = None
        self.auto_connect_thread = None
    
    def _get_current_device_ip_via_adb(self):
        """通过ADB获取设备当前实际IP地址
        
        Returns:
            str: 设备IP地址，如果获取失败返回None
        """
        return self.device_manager.get_current_device_ip_via_adb()
    
    def _wifi_reconnect_attempt(self, device_ip, wifi_ssid, wifi_password, rtsp_0, rtsp_1):
        """WiFi自动重连尝试（QThread后台任务）"""
        if getattr(self, "wifi_reconnect_thread", None) and self.wifi_reconnect_thread.isRunning():
            log_manager.info("[AUTO] WiFi重连任务已在运行，跳过重复启动")
            return

        self.wifi_reconnect_thread = QThread()
        self.wifi_reconnect_worker = WiFiReconnectWorker(
            self.device_manager,
            device_ip,
            wifi_ssid,
            wifi_password,
            rtsp_0,
            rtsp_1,
        )
        self.wifi_reconnect_worker.moveToThread(self.wifi_reconnect_thread)
        self.wifi_reconnect_thread.started.connect(self.wifi_reconnect_worker.run)
        self.wifi_reconnect_worker.finished.connect(self._on_wifi_reconnect_finished, Qt.QueuedConnection)
        self.wifi_reconnect_worker.finished.connect(self.wifi_reconnect_thread.quit)
        self.wifi_reconnect_worker.finished.connect(self.wifi_reconnect_worker.deleteLater)
        self.wifi_reconnect_thread.finished.connect(self.wifi_reconnect_thread.deleteLater)
        self.wifi_reconnect_thread.finished.connect(self._clear_wifi_reconnect_refs)
        self.wifi_reconnect_thread.start()

    def _on_wifi_reconnect_finished(self, success, device_ip, rtsp_0, rtsp_1, message):
        """WiFi重连完成后回到主线程更新界面。"""
        if success:
            self._on_auto_connect_success(device_ip, rtsp_0, rtsp_1, message)
        else:
            self._on_auto_connect_failed(device_ip, message)

    def _clear_wifi_reconnect_refs(self):
        """释放WiFi重连线程引用。"""
        self.wifi_reconnect_worker = None
        self.wifi_reconnect_thread = None

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

        try:
            wifi_ssid = ''
            wifi_password = ''
            if os.path.exists(self.device_config_file):
                with open(self.device_config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                wifi_ssid = saved_config.get('wifi_ssid', '')
                wifi_password = saved_config.get('wifi_password', '')
            self.save_device_config(device_ip, rtsp_0, rtsp_1, wifi_ssid, wifi_password)
        except Exception as e:
            log_manager.warning(f"[AUTO] 自动连接后更新设备配置失败: {e}")
        
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
        
        # 自动加载追踪模式
        self.load_track_modes()
        
    def save_device_config(self, device_ip, rtsp_0, rtsp_1, wifi_ssid='', wifi_password=''):
        """保存设备配置到本地文件"""
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
