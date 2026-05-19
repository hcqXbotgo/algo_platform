# 算法验证上位机平台

一个功能完整的Python GUI应用程序，用于管理和验证嵌入式设备上的AI算法模型。

## 功能特性

### 1. 模型管理
- 📤 **RKNN模型推送**：通过SSH/ADB将模型文件推送到设备 `/oem/usr/models` 目录
- 📋 **模型列表查看**：实时查看设备上已部署的模型
- 🔄 **模型替换**：一键替换旧模型文件

### 2. 参数配置
- ⚙️ **配置文件编辑**：可视化编辑 `model_config.json` 和 `xbotgo_media.ini`
- 📝 **JSON/INI格式支持**：支持多种配置文件格式
- 🚀 **配置推送**：将修改后的配置推送到设备并自动生效

### 3. 性能监控
- 📊 **实时监控**：
  - NPU占用率（`/sys/kernel/debug/rknpu/load`）
  - CPU占用率
  - 内存使用情况
  - DDR带宽（可配置频率，默认1848MHz）
- 📈 **趋势图表**：动态显示性能指标变化曲线
- 💾 **数据导出**：导出历史性能数据为CSV格式

### 4. 日志分析
- 🔍 **智能解析**：自动解析推理日志，提取耗时信息
- 📉 **可视化**：生成每帧推理耗时曲线图
- 📊 **统计分析**：计算平均耗时、最大耗时、标准差等指标
- 📄 **CSV导出**：一键导出详细数据和汇总报告

### 5. 视频源管理
- 📹 **RTSP流连接**：支持双路摄像头输入
  - `rtsp://IP/live/0` - 通道0
  - `rtsp://IP/live/1` - 通道1
- 🎬 **本地视频上传**：上传MP4文件到设备 `/userdata` 目录
- 🔄 **视频源切换**：在本地视频和RTSP流之间切换
- 🌐 **设备IP配置**：自动获取或手动设置设备IP

### 6. 算法控制
- 🎯 **MQTT追踪控制**：发送追踪模式切换指令
- 📡 **多模式支持**：从配置文件加载所有追踪模式
- ⏹️ **启停控制**：启动/停止追踪算法
- 🔄 **进程管理**：重启/停止 `multi_media` 进程

### 7. WiFi配置
- 📶 **WiFi连接**：通过脚本连接指定WiFi网络
- 💾 **配置固化**：保存WiFi配置实现自动重连
- 🔍 **网络扫描**：查看可用WiFi网络（扩展功能）

## 安装说明

### 1. 环境要求
- Python 3.7+
- PyQt5
- 依赖包见 `requirements.txt`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行程序

```bash
python algorithm_platform.py
```

## 使用指南

### 模型管理
1. 切换到"模型管理"标签页
2. 点击"浏览..."选择 `.rknn` 模型文件
3. 输入设备IP地址（默认：172.16.110.6）
4. 选择连接方式（SSH或ADB）
5. 点击"推送模型到设备"
6. 推送完成后点击"重启multi_media进程"使新模型生效

### 参数配置
1. 切换到"参数配置"标签页
2. 加载配置文件（`model_config.json` 或 `xbotgo_media.ini`）
3. 在编辑器中修改参数
4. 点击"推送到设备"
5. 重启 `multi_media` 进程应用新配置

### 性能监控
1. 切换到"性能监控"标签页
2. 设置采样间隔（默认2秒）和DDR频率（默认1848MHz）
3. 点击"开始监控"
4. 实时查看各项指标和趋势图
5. 点击"停止监控"结束采集

### 日志分析
1. 切换到"日志分析"标签页
2. 选择日志文件（包含推理耗时信息）
3. 点击"分析日志"
4. 查看统计结果和耗时曲线
5. 点击"导出CSV"保存分析结果

### 视频源管理
1. 切换到"视频源管理"标签页
2. **RTSP流**：
   - 输入设备IP
   - 选择要连接的通道
   - 点击"连接RTSP流"
3. **本地视频**：
   - 选择MP4文件
   - 点击"上传视频到设备"
4. **视频源切换**：
   - 选择视频源类型
   - 点击"应用视频源设置"

### 算法控制
1. 切换到"算法控制"标签页
2. **MQTT连接**：
   - 输入Broker地址和端口
   - 点击"连接MQTT"
3. **启动追踪**：
   - 选择追踪模式（从配置文件加载）
   - 点击"启动追踪"
4. **WiFi配置**：
   - 输入SSID和密码
   - 点击"连接WiFi并固化配置"

## 配置文件说明

### model_config.json
包含所有追踪模式的配置：
- `id`: 模式ID（MQTT控制时使用）
- `desc`: 模式描述
- `models`: 模型列表及参数
- `motFrameRate`: 追踪帧率
- `pitchInitialAngle`: 初始角度

### xbotgo_media.ini
媒体配置：
```ini
[rtsp]
enable = 1          # 启用RTSP

[uvc]
enable = 0

[video_src]
source = rtsp       # 视频源：rtsp 或 local
```

## MQTT协议

### 追踪控制
- **Topic**: `track`
- **Payload**: 单字节，对应 `model_config.json` 中的 `id` 字段
  - `0`: 停止追踪
  - `1-255`: 启动对应ID的追踪模式

## 设备命令参考

### 性能监控
```bash
# NPU占用率
cat /sys/kernel/debug/rknpu/load

# DDR带宽（需指定频率）
./rk-msch-probe-for-user-64bit-1 -c rk3576 -f 1848000000

# CPU和内存
top -bn1
free -m
```

### 进程管理
```bash
# 停止进程
killall multi_media

# 启动进程
cd /oem/usr/bin && ./multi_media &
```

### WiFi配置
```bash
# 连接WiFi
wifi-connect.sh <SSID> <PASSWORD>

# 保存配置（根据实际设备调整）
wifi-save-config
```

## 项目结构

```
模型验证平台/
├── algorithm_platform.py    # 主程序
├── device_manager.py        # 设备管理模块
├── performance_monitor.py   # 性能监控模块
├── log_analyzer.py         # 日志分析模块
├── video_manager.py        # 视频管理模块
├── mqtt_controller.py      # MQTT控制模块
├── wifi_manager.py         # WiFi管理模块
├── requirements.txt        # 依赖列表
├── model_config.json       # 追踪模式配置
├── xbotgo_media.ini       # 媒体配置
└── ana.py                  # 原始日志分析脚本（参考）
```

## 扩展开发

### 添加新的性能指标
在 `performance_monitor.py` 中添加新的监控方法：

```python
def _get_your_metric(self):
    output = self._execute_command("your_command")
    # 解析输出
    return value
```

### 添加新的日志格式支持
在 `log_analyzer.py` 中修改正则表达式以匹配新的日志格式。

### 自定义追踪模式
在 `model_config.json` 中添加新的mode配置项。

## 常见问题

**Q: SSH连接失败？**
- 检查设备IP是否正确
- 确认设备SSH服务已启动
- 检查网络连接

**Q: RTSP流无法播放？**
- 确认设备上RTSP服务已启用
- 检查防火墙设置
- 验证RTSP URL格式

**Q: 模型推送后不生效？**
- 确保已重启 `multi_media` 进程
- 检查配置文件中的模型路径是否正确

## 技术支持

如有问题或建议，请联系开发团队。

---
© 2024 Algorithm Validation Team
