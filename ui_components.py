# -*- coding: utf-8 -*-
"""
UI组件模块
功能：将主程序的UI创建逻辑拆分为独立模块，提高代码可维护性
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QTextEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QSpinBox, QDoubleSpinBox, QFrame, QAbstractItemView,
    QMessageBox, QListWidget, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ModelConfigTab:
    """模型与配置标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建模型与配置合并标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ========== 上半部分：模型管理 ==========
        model_group = QGroupBox("📦 模型文件管理")
        model_layout = QVBoxLayout()
        
        # 模型文件选择
        file_select_layout = QHBoxLayout()
        parent.model_file_edit = QLineEdit()
        parent.model_file_edit.setReadOnly(True)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(parent.browse_model_file)
        file_select_layout.addWidget(QLabel("RKNN模型:"))
        file_select_layout.addWidget(parent.model_file_edit)
        file_select_layout.addWidget(browse_btn)
        model_layout.addLayout(file_select_layout)
        
        # 推送按钮
        push_model_btn = QPushButton("📤 推送模型到设备")
        push_model_btn.clicked.connect(parent.push_model_to_device)
        push_model_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold;")
        model_layout.addWidget(push_model_btn)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # 当前模型列表（带删除功能）
        list_group = QGroupBox("📋 已部署模型")
        list_layout = QVBoxLayout()
        
        parent.model_table = QTableWidget()
        parent.model_table.setColumnCount(4)
        parent.model_table.setHorizontalHeaderLabels(["模型名称", "大小", "修改时间", "操作"])
        parent.model_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        list_layout.addWidget(parent.model_table)
        
        refresh_btn = QPushButton("🔄 刷新模型列表")
        refresh_btn.clicked.connect(parent.refresh_model_list)
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
        parent.config_file_edit = QLineEdit()
        parent.config_file_edit.setReadOnly(True)
        config_browse_btn = QPushButton("浏览...")
        config_browse_btn.clicked.connect(parent.browse_config_file)
        config_file_layout.addWidget(QLabel("配置文件:"))
        config_file_layout.addWidget(parent.config_file_edit)
        config_file_layout.addWidget(config_browse_btn)
        config_layout.addLayout(config_file_layout)
        
        load_config_btn = QPushButton("📂 加载配置")
        load_config_btn.clicked.connect(parent.load_config)
        config_layout.addWidget(load_config_btn)
        
        load_device_config_btn = QPushButton("🔄 从设备加载")
        load_device_config_btn.clicked.connect(parent.load_config_from_device)
        load_device_config_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        config_layout.addWidget(load_device_config_btn)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # 配置编辑器
        edit_group = QGroupBox("📝 配置编辑器")
        edit_layout = QVBoxLayout()
        
        parent.config_text_edit = QTextEdit()
        parent.config_text_edit.setFont(QFont("Consolas", 10))
        edit_layout.addWidget(parent.config_text_edit)
        
        btn_layout = QHBoxLayout()
        save_local_btn = QPushButton("💾 保存到本地")
        save_local_btn.clicked.connect(parent.save_config_local)
        btn_layout.addWidget(save_local_btn)
        
        push_config_btn = QPushButton("📤 推送到设备")
        push_config_btn.clicked.connect(parent.push_config_to_device)
        push_config_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px; font-weight: bold;")
        btn_layout.addWidget(push_config_btn)
        
        edit_layout.addLayout(btn_layout)
        edit_group.setLayout(edit_layout)
        layout.addWidget(edit_group)
        
        return widget


class PerformanceTab:
    """性能监控标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建性能监控标签页（包含算法控制和进程控制）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 控制面板
        control_group = QGroupBox("监控控制")
        control_layout = QFormLayout()
        
        parent.monitor_interval_spin = QSpinBox()
        parent.monitor_interval_spin.setRange(1, 10)
        parent.monitor_interval_spin.setValue(2)
        control_layout.addRow("采样间隔(秒):", parent.monitor_interval_spin)
        
        parent.ddr_freq_spin = QSpinBox()
        parent.ddr_freq_spin.setRange(1000, 3000)
        parent.ddr_freq_spin.setValue(1848)
        control_layout.addRow("DDR频率(MHz):", parent.ddr_freq_spin)
        
        # 创建单个按钮，根据状态切换文本
        parent.monitor_btn = QPushButton("开始监控")
        parent.monitor_btn.clicked.connect(parent.toggle_monitoring)
        parent.monitor_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        control_layout.addRow(parent.monitor_btn)
        
        # 监控状态标记
        parent.is_monitoring = False
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # MQTT状态显示（只读，自动连接）
        mqtt_group = QGroupBox("MQTT状态")
        mqtt_layout = QVBoxLayout()
        
        parent.mqtt_status_label = QLabel("🔌 MQTT: 未连接\n💡 提示: 设备配置后将自动连接MQTT")
        parent.mqtt_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
        """)
        parent.mqtt_status_label.setWordWrap(True)
        mqtt_layout.addWidget(parent.mqtt_status_label)
        
        mqtt_group.setLayout(mqtt_layout)
        layout.addWidget(mqtt_group)
        
        # 追踪模式选择（使用单个按钮切换状态）
        track_group = QGroupBox("追踪模式")
        track_layout = QFormLayout()
        
        parent.track_mode_combo = QComboBox()
        # 从配置文件加载模式
        parent.load_track_modes()
        track_layout.addRow("追踪模式:", parent.track_mode_combo)
        
        # 创建单个按钮，根据状态切换文本
        parent.track_btn = QPushButton("启动追踪")
        parent.track_btn.clicked.connect(parent.toggle_tracking)
        parent.track_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        track_layout.addRow(parent.track_btn)
        
        # 追踪状态标记
        parent.is_tracking = False
        
        track_group.setLayout(track_layout)
        layout.addWidget(track_group)
        
        # 进程控制
        process_group = QGroupBox("进程控制")
        process_layout = QHBoxLayout()
        
        restart_process_btn = QPushButton("重启multi_media进程")
        restart_process_btn.clicked.connect(parent.restart_media_process)
        restart_process_btn.setStyleSheet("background-color: #FF9800; color: white;")
        process_layout.addWidget(restart_process_btn)
        
        kill_process_btn = QPushButton("停止multi_media进程")
        kill_process_btn.clicked.connect(parent.kill_media_process)
        kill_process_btn.setStyleSheet("background-color: #f44336; color: white;")
        process_layout.addWidget(kill_process_btn)
        
        process_group.setLayout(process_layout)
        layout.addWidget(process_group)
        
        # 实时数据显示
        data_group = QGroupBox("实时数据")
        data_layout = QVBoxLayout()
        
        parent.perf_table = QTableWidget()
        parent.perf_table.setColumnCount(2)
        parent.perf_table.setHorizontalHeaderLabels(["指标", "数值"])
        parent.perf_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        data_layout.addWidget(parent.perf_table)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # 图表区域
        chart_group = QGroupBox("性能趋势图")
        chart_layout = QVBoxLayout()
        
        parent.perf_figure = Figure(figsize=(10, 4))
        parent.perf_canvas = FigureCanvas(parent.perf_figure)
        chart_layout.addWidget(parent.perf_canvas)
        
        # 导出图片按钮
        export_perf_btn = QPushButton("💾 导出性能趋势图")
        export_perf_btn.clicked.connect(parent.export_performance_plot)
        export_perf_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        chart_layout.addWidget(export_perf_btn)
        
        chart_group.setLayout(chart_layout)
        layout.addWidget(chart_group)
        
        return widget


class LogAnalysisTab:
    """日志分析标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建日志分析标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ========== 上半部分：日志文件选择 ==========
        file_group = QGroupBox("📄 日志文件选择")
        file_layout = QVBoxLayout()
        
        # 日志文件输入框和按钮
        file_select_layout = QHBoxLayout()
        parent.log_file_edit = QLineEdit()
        parent.log_file_edit.setReadOnly(True)
        log_browse_btn = QPushButton("本地浏览...")
        log_browse_btn.clicked.connect(parent.browse_log_file)
        device_log_btn = QPushButton("从设备选择...")
        device_log_btn.clicked.connect(parent.load_device_logs)
        device_log_btn.setStyleSheet("background-color: #2196F3; color: white;")
        
        file_select_layout.addWidget(QLabel("日志文件:"))
        file_select_layout.addWidget(parent.log_file_edit)
        file_select_layout.addWidget(log_browse_btn)
        file_select_layout.addWidget(device_log_btn)
        file_layout.addLayout(file_select_layout)
        
        # 分析按钮
        analyze_btn = QPushButton(" 分析日志")
        analyze_btn.clicked.connect(parent.analyze_log)
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
        
        parent.device_log_table = QTableWidget()
        parent.device_log_table.setColumnCount(4)
        parent.device_log_table.setHorizontalHeaderLabels(["日志文件名", "大小", "修改时间", "操作"])
        parent.device_log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        parent.device_log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        parent.device_log_table.setStyleSheet("""
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
        list_layout.addWidget(parent.device_log_table)
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton(" 刷新日志列表")
        refresh_btn.clicked.connect(parent.load_device_logs)
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
        
        parent.result_table = QTableWidget()
        parent.result_table.setColumnCount(7)
        parent.result_table.setHorizontalHeaderLabels([
            "模型名称", 
            "推理平均(ms)", 
            "总耗时平均(ms)", 
            "最大耗时(ms)",
            "帧数",
            "推理标准差(ms)",
            "总耗时标准差(ms)"
        ])
        parent.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        parent.result_table.setStyleSheet("""
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
        result_layout.addWidget(parent.result_table)
        
        export_csv_btn = QPushButton("💾 导出CSV")
        export_csv_btn.clicked.connect(parent.export_csv)
        result_layout.addWidget(export_csv_btn)
        
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)
        
        # 图表显示
        plot_group = QGroupBox("📈 耗时曲线")
        plot_layout = QVBoxLayout()
        
        parent.log_figure = Figure(figsize=(10, 5))
        parent.log_canvas = FigureCanvas(parent.log_figure)
        plot_layout.addWidget(parent.log_canvas)
        
        # 导出图片按钮
        export_plot_btn = QPushButton("💾 导出图片")
        export_plot_btn.clicked.connect(parent.export_log_plot)
        export_plot_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        plot_layout.addWidget(export_plot_btn)
        
        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        return widget


class VideoTab:
    """视频源管理标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建视频源管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        status_group = QGroupBox("设备视频源")
        status_layout = QFormLayout()
        parent.video_device_ip_label = QLabel("未连接设备")
        parent.video_device_ip_label.setStyleSheet("color: #7f8c8d; padding: 5px;")
        parent.rtsp_device_ip_label = parent.video_device_ip_label
        status_layout.addRow("设备IP:", parent.video_device_ip_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # 本地视频上传
        local_group = QGroupBox("本地视频管理")
        local_layout = QFormLayout()
        
        parent.video_file_edit = QLineEdit()
        parent.video_file_edit.setReadOnly(True)
        video_browse_btn = QPushButton("浏览...")
        video_browse_btn.clicked.connect(parent.browse_video_file)
        video_file_layout = QHBoxLayout()
        video_file_layout.addWidget(parent.video_file_edit)
        video_file_layout.addWidget(video_browse_btn)
        local_layout.addRow("视频文件:", video_file_layout)
        
        upload_video_btn = QPushButton("上传视频到设备")
        upload_video_btn.clicked.connect(parent.upload_video_to_device)
        local_layout.addRow(upload_video_btn)
        
        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        # 设备视频列表
        device_video_group = QGroupBox("设备 /userdata 视频文件")
        device_video_layout = QVBoxLayout()
        refresh_video_btn = QPushButton("刷新设备视频列表")
        refresh_video_btn.clicked.connect(parent.refresh_device_videos)
        device_video_layout.addWidget(refresh_video_btn)

        parent.device_video_list = QListWidget()
        parent.device_video_list.setSelectionMode(QAbstractItemView.SingleSelection)
        parent.device_video_list.setMinimumHeight(180)
        device_video_layout.addWidget(parent.device_video_list)

        parent.selected_device_video_label = QLabel("未选择视频")
        parent.selected_device_video_label.setStyleSheet("color: #7f8c8d; padding: 4px;")
        device_video_layout.addWidget(parent.selected_device_video_label)
        parent.device_video_list.itemSelectionChanged.connect(parent.on_device_video_selected)

        device_video_group.setLayout(device_video_layout)
        layout.addWidget(device_video_group)
        
        # 视频源切换
        source_group = QGroupBox("视频源选择")
        source_layout = QVBoxLayout()
        parent.video_source_group = QButtonGroup(parent)
        parent.camera_source_radio = QRadioButton("摄像头")
        parent.file_source_radio = QRadioButton("本地视频（设备 /userdata）")
        parent.camera_source_radio.setChecked(True)
        parent.video_source_group.addButton(parent.camera_source_radio)
        parent.video_source_group.addButton(parent.file_source_radio)
        source_layout.addWidget(parent.camera_source_radio)
        source_layout.addWidget(parent.file_source_radio)

        apply_source_btn = QPushButton("应用视频源设置")
        apply_source_btn.clicked.connect(parent.apply_video_source)
        source_layout.addWidget(apply_source_btn)

        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        # 追踪结果合成
        merge_group = QGroupBox("追踪结果合成与播放")
        merge_layout = QVBoxLayout()
        merge_btn_layout = QHBoxLayout()
        pull_merge_btn = QPushButton("拉取追踪JSON并合成带框视频")
        pull_merge_btn.clicked.connect(parent.merge_tracking_video)
        parent.open_merged_video_btn = QPushButton("播放合成视频")
        parent.open_merged_video_btn.clicked.connect(parent.play_merged_video)
        parent.open_merged_video_btn.setEnabled(False)
        parent.fullscreen_merged_video_btn = QPushButton("全屏播放")
        parent.fullscreen_merged_video_btn.clicked.connect(parent.play_merged_video_fullscreen)
        parent.fullscreen_merged_video_btn.setEnabled(False)
        merge_btn_layout.addWidget(pull_merge_btn)
        merge_btn_layout.addWidget(parent.open_merged_video_btn)
        merge_btn_layout.addWidget(parent.fullscreen_merged_video_btn)
        merge_layout.addLayout(merge_btn_layout)

        parent.merge_progress_bar = QProgressBar()
        parent.merge_progress_bar.setRange(0, 100)
        parent.merge_progress_bar.setValue(0)
        merge_layout.addWidget(parent.merge_progress_bar)

        parent.merge_status_label = QLabel("等待合成")
        parent.merge_status_label.setStyleSheet("color: #7f8c8d; padding: 4px;")
        merge_layout.addWidget(parent.merge_status_label)

        merge_group.setLayout(merge_layout)
        layout.addWidget(merge_group)
        
        return widget


class RTMPTab:
    """RTMP直播标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建RTMP直播标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # RTMP服务器配置组
        rtmp_group = QGroupBox("RTMP服务器配置")
        rtmp_layout = QFormLayout()
        
        parent.rtmp_url_edit = QLineEdit("rtmp://192.168.17.108/live/test")
        parent.rtmp_url_edit.setPlaceholderText("例如: rtmp://192.168.17.108/live/test")
        rtmp_layout.addRow("服务器地址:", parent.rtmp_url_edit)
        
        parent.rtmp_quality_combo = QComboBox()
        parent.rtmp_quality_combo.addItems(["720P (流畅)", "1080P (高清)"])
        parent.rtmp_quality_combo.setCurrentIndex(0)
        rtmp_layout.addRow("画质选择:", parent.rtmp_quality_combo)
        
        rtmp_group.setLayout(rtmp_layout)
        layout.addWidget(rtmp_group)
        
        # 推流控制组
        control_group = QGroupBox("推流控制")
        control_layout = QVBoxLayout()
        
        # 状态显示
        parent.rtmp_status_label = QLabel("📺 RTMP推流状态: 未启动")
        parent.rtmp_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
            font-size: 14px;
        """)
        parent.rtmp_status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(parent.rtmp_status_label)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        
        start_stream_btn = QPushButton("▶️ 开始直播")
        start_stream_btn.clicked.connect(parent.start_rtmp_streaming)
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
        stop_stream_btn.clicked.connect(parent.stop_rtmp_streaming)
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


class WiFiPerfTab:
    """WiFi性能测试标签页"""
    
    @staticmethod
    def create_tab(parent):
        """创建WiFi性能测试标签页"""
        from PyQt5.QtGui import QFont
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ========== 设备信息组 ==========
        info_group = QGroupBox("📡 WiFi设备信息")
        info_layout = QFormLayout()
        
        parent.wifi_device_ip_label = QLabel("未连接设备")
        parent.wifi_device_ip_label.setStyleSheet("color: #7f8c8d; padding: 5px;")
        info_layout.addRow("设备IP:", parent.wifi_device_ip_label)
        
        parent.wifi_rssi_label = QLabel("N/A")
        parent.wifi_rssi_label.setStyleSheet("color: #2c3e50; font-weight: bold; padding: 5px;")
        info_layout.addRow("信号强度(RSSI):", parent.wifi_rssi_label)
        
        parent.wifi_speed_label = QLabel("N/A")
        parent.wifi_speed_label.setStyleSheet("color: #2c3e50; font-weight: bold; padding: 5px;")
        info_layout.addRow("协商速率:", parent.wifi_speed_label)
        
        refresh_wifi_btn = QPushButton("🔄 刷新WiFi信息")
        refresh_wifi_btn.clicked.connect(parent.refresh_wifi_info)
        refresh_wifi_btn.setStyleSheet("background-color: #3498db; color: white; padding: 8px; font-weight: bold;")
        info_layout.addRow(refresh_wifi_btn)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # ========== 测试配置组 ==========
        config_group = QGroupBox("⚙️ 测试配置")
        config_layout = QFormLayout()
        
        # 带宽选择
        parent.bandwidth_combo = QComboBox()
        parent.bandwidth_combo.addItems(["单点测试", "多点扫描"])
        parent.bandwidth_combo.currentIndexChanged.connect(parent.on_test_mode_changed)
        config_layout.addRow("测试模式:", parent.bandwidth_combo)
        
        # 单点测试配置
        single_config_widget = QWidget()
        single_config_layout = QFormLayout(single_config_widget)
        
        parent.single_bandwidth_spin = QSpinBox()
        parent.single_bandwidth_spin.setRange(1, 100)
        parent.single_bandwidth_spin.setValue(10)
        parent.single_bandwidth_spin.setSuffix(" Mbps")
        single_config_layout.addRow("目标带宽:", parent.single_bandwidth_spin)
        
        config_layout.addRow(single_config_widget)
        parent.single_config_widget = single_config_widget
        
        # 多点扫描配置（默认隐藏）
        multi_config_widget = QWidget()
        multi_config_layout = QHBoxLayout(multi_config_widget)
        
        multi_config_layout.addWidget(QLabel("带宽范围:"))
        parent.multi_bw_start_spin = QSpinBox()
        parent.multi_bw_start_spin.setRange(1, 100)
        parent.multi_bw_start_spin.setValue(5)
        parent.multi_bw_start_spin.setSuffix(" Mbps")
        multi_config_layout.addWidget(parent.multi_bw_start_spin)
        
        multi_config_layout.addWidget(QLabel("至"))
        parent.multi_bw_end_spin = QSpinBox()
        parent.multi_bw_end_spin.setRange(1, 100)
        parent.multi_bw_end_spin.setValue(50)
        parent.multi_bw_end_spin.setSuffix(" Mbps")
        multi_config_layout.addWidget(parent.multi_bw_end_spin)
        
        multi_config_layout.addWidget(QLabel("步长:"))
        parent.multi_bw_step_spin = QSpinBox()
        parent.multi_bw_step_spin.setRange(1, 20)
        parent.multi_bw_step_spin.setValue(5)
        parent.multi_bw_step_spin.setSuffix(" Mbps")
        multi_config_layout.addWidget(parent.multi_bw_step_spin)
        
        multi_config_layout.addStretch()
        
        config_layout.addRow(multi_config_widget)
        parent.multi_config_widget = multi_config_widget
        parent.multi_config_widget.setVisible(False)
        
        # 测试时长
        parent.test_duration_spin = QSpinBox()
        parent.test_duration_spin.setRange(5, 60)
        parent.test_duration_spin.setValue(10)
        parent.test_duration_spin.setSuffix(" 秒")
        config_layout.addRow("测试时长:", parent.test_duration_spin)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # ========== 控制按钮组 ==========
        control_group = QGroupBox("🎮 测试控制")
        control_layout = QVBoxLayout()
        
        # 状态显示
        parent.wifi_test_status_label = QLabel("⏸️ 测试状态: 就绪")
        parent.wifi_test_status_label.setStyleSheet("""
            padding: 15px; 
            background-color: #ecf0f1; 
            border-radius: 5px;
            color: #7f8c8d;
            font-size: 14px;
        """)
        parent.wifi_test_status_label.setAlignment(Qt.AlignCenter)
        parent.wifi_test_status_label.setWordWrap(True)
        control_layout.addWidget(parent.wifi_test_status_label)
        
        # 进度条
        parent.wifi_test_progress = QProgressBar()
        parent.wifi_test_progress.setValue(0)
        parent.wifi_test_progress.setTextVisible(True)
        control_layout.addWidget(parent.wifi_test_progress)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        
        parent.start_test_btn = QPushButton("▶️ 开始测试")
        parent.start_test_btn.clicked.connect(parent.start_wifi_perf_test)
        parent.start_test_btn.setStyleSheet("""
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
        btn_layout.addWidget(parent.start_test_btn)
        
        parent.stop_test_btn = QPushButton("⏹️ 停止测试")
        parent.stop_test_btn.clicked.connect(parent.stop_wifi_perf_test)
        parent.stop_test_btn.setEnabled(False)
        parent.stop_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        btn_layout.addWidget(parent.stop_test_btn)
        
        control_layout.addLayout(btn_layout)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # ========== 实时结果展示组 ==========
        result_group = QGroupBox("📊 实时测试结果")
        result_layout = QVBoxLayout()
        
        # 结果表格
        parent.wifi_result_table = QTableWidget()
        parent.wifi_result_table.setColumnCount(8)
        parent.wifi_result_table.setHorizontalHeaderLabels([
            "目标带宽(Mbps)", "实际吞吐量(Mbps)", "抖动(ms)", 
            "丢包率(%)", "延迟(ms)", "RSSI(dBm)", "协商速率(Mbps)", "时间"
        ])
        parent.wifi_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        parent.wifi_result_table.setStyleSheet("""
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
        result_layout.addWidget(parent.wifi_result_table)
        
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)
        
        # ========== 图表展示组 ==========
        chart_group = QGroupBox("📈 性能趋势图")
        chart_layout = QVBoxLayout()
        
        parent.wifi_perf_figure = Figure(figsize=(14, 8))
        parent.wifi_perf_canvas = FigureCanvas(parent.wifi_perf_figure)
        parent.wifi_perf_canvas.setMinimumHeight(420)
        chart_layout.addWidget(parent.wifi_perf_canvas)
        
        chart_group.setLayout(chart_layout)
        layout.addWidget(chart_group)
        
        # ========== 导出按钮组 ==========
        export_group = QGroupBox("💾 数据导出")
        export_layout = QHBoxLayout()
        
        export_csv_btn = QPushButton("📄 导出CSV报告")
        export_csv_btn.clicked.connect(parent.export_wifi_perf_csv)
        export_csv_btn.setStyleSheet("background-color: #3498db; color: white; padding: 10px; font-weight: bold;")
        export_layout.addWidget(export_csv_btn)

        export_curve_btn = QPushButton("🖼️ 导出曲线图")
        export_curve_btn.clicked.connect(parent.export_wifi_perf_plot)
        export_curve_btn.setStyleSheet("background-color: #2ecc71; color: white; padding: 10px; font-weight: bold;")
        export_layout.addWidget(export_curve_btn)
        
        clear_results_btn = QPushButton("🗑️ 清空结果")
        clear_results_btn.clicked.connect(parent.clear_wifi_results)
        clear_results_btn.setStyleSheet("background-color: #95a5a6; color: white; padding: 10px; font-weight: bold;")
        export_layout.addWidget(clear_results_btn)
        
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)
        
        return widget
