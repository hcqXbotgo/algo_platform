# -*- coding: utf-8 -*-
"""
快速验证脚本 - 检查所有模块是否可以正常导入
"""

import sys

def check_module(name, display_name):
    """检查模块是否可以导入"""
    try:
        __import__(name)
        print(f"✓ {display_name:30} OK")
        return True
    except Exception as e:
        print(f"✗ {display_name:30} FAILED: {e}")
        return False

print("=" * 60)
print("Algorithm Validation Platform - Module Check")
print("=" * 60)
print()

all_ok = True

# 检查核心依赖
print("Core Dependencies:")
all_ok &= check_module('PyQt5', 'PyQt5')
all_ok &= check_module('matplotlib', 'Matplotlib')
all_ok &= check_module('numpy', 'NumPy')
all_ok &= check_module('cv2', 'OpenCV')
all_ok &= check_module('paramiko', 'Paramiko')
all_ok &= check_module('mqtt', 'Paho-MQTT')
print()

# 检查自定义模块
print("Custom Modules:")
all_ok &= check_module('device_manager', 'Device Manager')
all_ok &= check_module('performance_monitor', 'Performance Monitor')
all_ok &= check_module('log_analyzer', 'Log Analyzer')
all_ok &= check_module('video_manager', 'Video Manager')
all_ok &= check_module('mqtt_controller', 'MQTT Controller')
all_ok &= check_module('wifi_manager', 'WiFi Manager')
print()

print("=" * 60)
if all_ok:
    print("✓ All modules loaded successfully!")
    print("You can now run: python algorithm_platform.py")
else:
    print("✗ Some modules failed to load")
    print("Please fix the errors above before running the application")
print("=" * 60)
