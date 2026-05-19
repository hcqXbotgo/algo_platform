# 算法验证上位机平台 - 快速开始指南

## ⚡ 三步启动（30秒内完成）

### ✅ 第一步：已完成！
依赖包已经全部安装成功：
- PyQt5 ✓
- matplotlib ✓  
- numpy ✓
- paramiko ✓
- paho-mqtt ✓
- opencv-python ✓

### 🎯 第二步：启动程序

**方法A - 双击启动（最简单）**
```
双击文件: start.bat
```

**方法B - 命令行启动**
```bash
cd "c:\falcon\算法SDK\模型验证平台"
python algorithm_platform.py
```

### 📖 第三步：开始使用

程序打开后，您会看到6个功能标签页。

---

## 🎯 常用操作速查

### 推送新模型
1. 点击"模型管理"标签
2. 浏览选择 `.rknn` 文件
3. 输入设备IP（默认：172.16.110.6）
4. 点击"推送模型到设备"
5. 切换到"算法控制" → 重启multi_media进程

### 监控性能
1. 点击"性能监控"标签
2. 点击"开始监控"
3. 实时查看NPU/CPU/内存曲线

### 分析日志
1. 点击"日志分析"标签
2. 选择日志文件
3. 点击"分析日志"
4. 查看统计和图表

---

## 🔧 故障排除

### 问题：双击start.bat没反应
**解决**: 
```bash
# 在命令行中运行，查看错误信息
cd "c:\falcon\算法SDK\模型验证平台"
python algorithm_platform.py
```

### 问题：提示缺少模块
**解决**:
```bash
pip install -r requirements.txt
```

### 问题：窗口打不开
**解决**: 检查Python版本
```bash
python --version
# 应该是 Python 3.7 或更高
```

---

## 📚 更多帮助

- **详细文档**: 查看 `README.md`
- **快速入门**: 查看 `QUICK_START.md`  
- **功能清单**: 查看 `FUNCTIONALITY.md`
- **代码结构**: 查看 `PROJECT_STRUCTURE.md`

---

## 🎉 准备好了！

**默认配置:**
- 设备IP: `172.16.110.6`
- DDR频率: `1848 MHz`
- 采样间隔: `2 秒`

如果您的配置不同，请在程序中修改。

**立即启动:** 
```bash
python algorithm_platform.py
```
