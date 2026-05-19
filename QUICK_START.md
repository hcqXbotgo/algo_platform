# 快速入门指南

## 🚀 5分钟快速开始

### 第一步：安装依赖

打开终端/命令提示符，进入项目目录：

```bash
cd "c:\falcon\算法SDK\模型验证平台"
pip install -r requirements.txt
```

或者双击运行 `start.bat`（会自动安装依赖）

### 第二步：启动程序

```bash
python algorithm_platform.py
```

或者双击运行 `start.bat`

### 第三步：基本使用

#### 场景1：推送新模型到设备

1. 点击 **"模型管理"** 标签页
2. 点击 **"浏览..."** 选择你的 `.rknn` 文件
3. 输入设备IP（例如：`172.16.110.6`）
4. 点击 **"推送模型到设备"**
5. 等待推送完成提示
6. 切换到 **"算法控制"** 标签页
7. 点击 **"重启multi_media进程"** 使新模型生效

#### 场景2：修改算法参数

1. 点击 **"参数配置"** 标签页
2. 点击 **"浏览..."** 选择 `model_config.json`
3. 点击 **"加载配置"**
4. 在编辑器中修改你需要的参数
5. 点击 **"推送到设备"**
6. 重启 `multi_media` 进程

#### 场景3：监控性能

1. 点击 **"性能监控"** 标签页
2. 设置采样间隔（默认2秒）
3. 设置DDR频率（默认1848MHz）
4. 点击 **"开始监控"**
5. 实时查看NPU、CPU、内存占用曲线
6. 点击 **"停止监控"** 结束

#### 场景4：分析推理日志

1. 点击 **"日志分析"** 标签页
2. 点击 **"浏览..."** 选择日志文件
3. 点击 **"分析日志"**
4. 查看统计表格和耗时曲线
5. 点击 **"导出CSV"** 保存结果

#### 场景5：连接摄像头

1. 点击 **"视频源管理"** 标签页
2. 输入设备IP
3. 勾选要连接的通道（通道0/通道1）
4. 点击 **"连接RTSP流"**

#### 场景6：切换追踪模式

1. 点击 **"算法控制"** 标签页
2. 配置MQTT Broker地址
3. 点击 **"连接MQTT"**
4. 在下拉框选择追踪模式
5. 点击 **"启动追踪"**

---

## 💡 常见使用场景

### 完整工作流程示例

假设你要测试一个新的足球检测模型：

**步骤1：准备阶段**
- 准备好训练好的 `Yolov5n_detect_xxx.rknn` 文件
- 确保设备已连接网络，IP为 `172.16.110.6`

**步骤2：推送模型**
1. 打开程序 → "模型管理"
2. 浏览选择你的RKNN文件
3. 输入IP → 推送
4. 看到成功提示

**步骤3：配置参数**
1. 切换到 "参数配置"
2. 加载 `model_config.json`
3. 找到对应的mode配置
4. 修改 `modelPath` 为你的模型文件名
5. 推送到设备

**步骤4：启动算法**
1. 切换到 "算法控制"
2. 重启 multi_media 进程
3. 等待几秒让进程启动
4. 选择对应的追踪模式（例如：soccer_5v5_over14）
5. 点击 "启动追踪"

**步骤5：监控性能**
1. 切换到 "性能监控"
2. 开始监控
3. 观察NPU占用是否正常（通常<80%）
4. 观察帧率是否稳定

**步骤6：分析日志**
1. 运行一段时间后停止算法
2. 获取设备上的日志文件
3. 在 "日志分析" 中加载日志
4. 分析推理耗时
5. 导出报告

---

## ⚙️ 配置说明

### 修改默认设备IP

编辑 `algorithm_platform.py`，找到：
```python
self.target_device_ip = QLineEdit("172.16.110.6")
```
改为你常用的IP地址。

### 修改DDR频率默认值

找到：
```python
self.ddr_freq_spin.setValue(1848)
```
改为你的设备支持的频率。

### 添加新的追踪模式

编辑 `model_config.json`，在 `modes` 数组中添加：
```json
{
  "id": 100,
  "desc": "my_custom_mode",
  "pitchInitialAngle": 0,
  "motFrameRate": 30,
  "models": [
    {
      "videoSrcType": "ANA_CAMERA",
      "modelPath": "your_model.rknn",
      "modelType": "YOLOV5_DETECTION",
      "modelSize": {"width": 1280, "height": 704},
      "labels": ["person", "ball"],
      "anchorInfo": [...]
    }
  ]
}
```

---

## 🔧 故障排查

### 问题1：SSH连接失败

**可能原因：**
- 设备未开机
- IP地址错误
- SSH服务未启动

**解决方法：**
```bash
# ping测试
ping 172.16.110.6

# 检查SSH端口
telnet 172.16.110.6 22
```

### 问题2：模型推送后不生效

**解决方法：**
1. 确认配置文件中的 `modelPath` 正确
2. 必须重启 multi_media 进程
3. 检查设备日志确认模型加载成功

### 问题3：RTSP流无法播放

**解决方法：**
1. 确认设备上RTSP服务已启动
2. 检查防火墙是否阻止
3. 尝试使用VLC播放器测试URL

### 问题4：MQTT连接失败

**解决方法：**
1. 确认MQTT Broker正在运行
2. 检查Broker地址和端口
3. 测试连接：
```bash
# 使用mosquitto测试
mosquitto_sub -h localhost -t test
```

---

## 📚 进阶技巧

### 批量推送多个模型

可以修改代码实现批量操作：
```python
# 在device_manager中添加批量推送方法
def push_multiple_models(self, model_files, device_ip):
    results = []
    for model_file in model_files:
        success, msg = self.push_model(model_file, device_ip)
        results.append((model_file, success, msg))
    return results
```

### 自定义性能告警

在 `performance_monitor.py` 中添加告警逻辑：
```python
def _check_alerts(self, npu_load, cpu_usage):
    if npu_load > 90:
        print("警告：NPU占用过高！")
    if cpu_usage > 85:
        print("警告：CPU占用过高！")
```

### 自动化测试脚本

创建自动测试流程：
```python
# 自动推送模型 → 重启进程 → 启动追踪 → 监控性能
def auto_test_workflow():
    device_manager.push_model("model.rknn", ip)
    device_manager.restart_media_process(ip)
    time.sleep(5)
    mqtt_controller.publish_track_command(1)
    performance_monitor.start_monitoring(ip)
```

---

## 🎯 最佳实践

1. **定期备份配置**：每次修改前备份原配置文件
2. **逐步测试**：一次只改动一个参数，便于定位问题
3. **记录日志**：保留所有测试日志用于对比分析
4. **性能基线**：先建立性能基线，再优化算法
5. **版本管理**：对模型文件进行版本编号

---

## 📞 获取帮助

- 查看 `README.md` 了解详细功能
- 查看 `PROJECT_STRUCTURE.md` 了解代码结构
- 查看 `examples.py` 学习扩展开发
- 运行 `test_environment.py` 检测环境问题

---

祝你使用愉快！🎉
