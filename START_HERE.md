# 启动说明 - START HERE

## ✅ 依赖已安装成功！

根据您的输出，所有必需的Python包已经成功安装：
- ✓ PyQt5 (GUI框架)
- ✓ matplotlib (绘图)
- ✓ numpy (数值计算)
- ✓ paramiko (SSH连接)
- ✓ paho-mqtt (MQTT通信)
- ✓ opencv-python (图像处理)

---

## 🚀 启动程序的3种方法

### 方法1：双击启动（推荐）
```
双击运行: start.bat
```

### 方法2：命令行启动
打开命令提示符(CMD)或PowerShell，输入：
```bash
cd "c:\falcon\算法SDK\模型验证平台"
python algorithm_platform.py
```

### 方法3：使用Python直接运行
在VSCode中：
1. 打开 `algorithm_platform.py`
2. 按 F5 或点击"运行"按钮

---

## 🔍 验证安装

如果想确认所有模块都正确安装，运行：
```bash
python check_modules.py
```

应该看到所有模块都显示 "OK"

---

## ⚠️ 如果启动失败

### 错误1: "ModuleNotFoundError"
**解决方案**: 重新安装依赖
```bash
pip install -r requirements.txt
```

### 错误2: "ImportError" 或 DLL 加载失败
**解决方案**: 可能需要更新某些包
```bash
pip install --upgrade PyQt5 matplotlib opencv-python
```

### 错误3: 程序窗口闪退
**解决方案**: 通过命令行查看错误信息
```bash
python algorithm_platform.py
```
查看具体的错误消息

---

## 📖 快速使用指南

程序启动后，您会看到一个图形界面，包含6个标签页：

1. **模型管理** - 推送RKNN模型到设备
2. **参数配置** - 编辑和推送配置文件
3. **性能监控** - 实时监控NPU/CPU/内存
4. **日志分析** - 分析推理耗时日志
5. **视频源管理** - 连接RTSP摄像头
6. **算法控制** - MQTT控制和WiFi配置

---

## 💡 提示

- 首次使用时，建议先阅读 `QUICK_START.md`
- 详细功能说明见 `README.md`
- 扩展开发参考 `examples.py`

---

## 🎯 现在就可以开始了！

**默认设备IP**: 172.16.110.6  
如果您的设备IP不同，请在各个标签页中修改

祝您使用愉快！🚀
