# 项目目录结构

模型验证平台/
│
├── 📄 README.md                      # 项目说明文档
├── 📄 requirements.txt               # Python依赖列表
├── 📄 start.bat                      # Windows启动脚本
├── 📄 test_environment.py            # 环境检测脚本
├── 📄 examples.py                    # 扩展开发示例
│
├── 🔧 algorithm_platform.py          # 主程序入口（GUI界面）
│   ├── 创建主窗口和菜单栏
│   ├── 集成6个功能标签页
│   └── 协调各个模块的工作
│
├── 📱 device_manager.py              # 设备管理模块
│   ├── SSH/ADB连接管理
│   ├── 文件推送（SCP/ADB）
│   ├── 进程控制（启动/停止）
│   └── 设备信息查询
│
├── 📊 performance_monitor.py         # 性能监控模块
│   ├── NPU占用率监控
│   ├── CPU占用率监控
│   ├── 内存使用监控
│   ├── DDR带宽监控
│   ├── 历史数据记录
│   └── 数据导出CSV
│
├── 📝 log_analyzer.py                # 日志分析模块
│   ├── 解析推理日志
│   ├── 统计耗时数据
│   ├── 生成CSV报告
│   └── 提供绘图数据
│
├── 🎬 video_manager.py               # 视频管理模块
│   ├── RTSP流连接
│   ├── 视频帧读取
│   └── 流状态管理
│
├── 📡 mqtt_controller.py             # MQTT控制模块
│   ├── MQTT连接管理
│   ├── 追踪命令发布
│   └── 主题订阅（扩展）
│
├── 📶 wifi_manager.py                # WiFi管理模块
│   ├── WiFi连接
│   ├── 配置固化
│   └── 网络扫描（扩展）
│
├── ⚙️ model_config.json              # 追踪模式配置文件
│   └── 定义所有可用的追踪算法模式
│
├── ⚙️ xbotgo_media.ini               # 媒体配置文件
│   └── RTSP、视频源等配置
│
└── 📜 ana.py                         # 原始日志分析脚本（参考）


## 模块依赖关系

```
algorithm_platform.py (主程序)
    ├── device_manager.py
    ├── performance_monitor.py
    ├── log_analyzer.py
    ├── video_manager.py
    ├── mqtt_controller.py
    └── wifi_manager.py
```

## 数据流向

1. **模型推送流程**:
   用户选择.rknn → device_manager.push_model() → SSH/ADB传输 → 设备/oem/usr/models/

2. **性能监控流程**:
   开始监控 → performance_monitor.start_monitoring() → 定时采集 → 更新UI图表

3. **日志分析流程**:
   选择日志文件 → log_analyzer.analyze() → 解析统计 → 生成CSV和图表

4. **算法控制流程**:
   选择追踪模式 → mqtt_controller.publish_track_command(id) → 发送MQTT消息 → 设备切换算法

## 关键类和方法

### DeviceManager
- `push_model(model_file, device_ip, connection_type)` - 推送模型
- `push_config(config_file, device_ip)` - 推送配置
- `restart_media_process(device_ip)` - 重启进程

### PerformanceMonitor
- `start_monitoring(device_ip, ddr_freq, interval)` - 开始监控
- `get_latest_data()` - 获取最新数据
- `get_history_data()` - 获取历史数据
- `export_data(filename)` - 导出数据

### LogAnalyzer
- `analyze(log_file)` - 分析日志
- `save_csv(frame_csv, summary_csv)` - 保存CSV
- `get_plot_data()` - 获取绘图数据

### MQTTController
- `connect(broker, port)` - 连接MQTT
- `publish_track_command(track_id)` - 发送追踪命令

### VideoManager
- `connect_rtsp(rtsp_urls)` - 连接RTSP流
- `read_frame(rtsp_url)` - 读取帧

### WiFiManager
- `connect_and_persist(device_ip, ssid, password)` - 连接并固化WiFi

## 扩展指南

### 添加新功能步骤:

1. **创建新模块** (可选)
   ```
   new_feature.py
   ```

2. **在主程序中导入**
   ```python
   from new_feature import NewFeature
   ```

3. **创建UI组件**
   ```python
   def create_new_tab(self):
       widget = QWidget()
       # ... 构建界面
       return widget
   ```

4. **添加到标签页**
   ```python
   tab_widget.addTab(self.create_new_tab(), "新功能")
   ```

### 自定义配置:

修改 `model_config.json` 添加新的追踪模式:
```json
{
  "id": 99,
  "desc": "custom_mode",
  "models": [...],
  "motFrameRate": 30
}
```

### 修改默认参数:

在 `algorithm_platform.py` 中修改:
- 默认设备IP: `self.target_device_ip.setText("your_ip")`
- 默认DDR频率: `self.ddr_freq_spin.setValue(your_value)`
- 默认采样间隔: `self.monitor_interval_spin.setValue(your_value)`
