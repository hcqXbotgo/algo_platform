# -*- coding: utf-8 -*-
"""
快速测试脚本 - 验证各个模块的基本功能
"""

import os
import sys


def test_imports():
    """测试依赖包是否安装"""
    print("=" * 50)
    print("测试依赖包导入...")
    print("=" * 50)
    
    packages = [
        ('PyQt5', 'pyqt5'),
        ('matplotlib', 'matplotlib'),
        ('numpy', 'numpy'),
        ('paramiko', 'paramiko'),
        ('paho.mqtt', 'paho-mqtt'),
        ('cv2', 'opencv-python')
    ]
    
    failed = []
    for package, pip_name in packages:
        try:
            __import__(package)
            print(f"✓ {package:20} - OK")
        except ImportError:
            print(f"✗ {package:20} - 未安装")
            failed.append(pip_name)
            
    if failed:
        print("\n以下包需要安装:")
        for pkg in failed:
            print(f"  - {pkg}")
        print("\n运行命令安装:")
        print(f"pip install {' '.join(failed)}")
        return False
    else:
        print("\n所有依赖包已就绪!")
        return True


def test_modules():
    """测试自定义模块"""
    print("\n" + "=" * 50)
    print("测试自定义模块...")
    print("=" * 50)
    
    modules = [
        'device_manager',
        'performance_monitor',
        'log_analyzer',
        'video_manager',
        'mqtt_controller',
        'wifi_manager'
    ]
    
    failed = []
    for module in modules:
        try:
            __import__(module)
            print(f"✓ {module:30} - OK")
        except ImportError as e:
            print(f"✗ {module:30} - 导入失败: {e}")
            failed.append(module)
            
    if failed:
        print(f"\n{len(failed)} 个模块导入失败")
        return False
    else:
        print("\n所有模块导入成功!")
        return True


def check_config_files():
    """检查配置文件"""
    print("\n" + "=" * 50)
    print("检查配置文件...")
    print("=" * 50)
    
    config_files = [
        'model_config.json',
        'xbotgo_media.ini',
        'ana.py'
    ]
    
    for filename in config_files:
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            print(f"✓ {filename:30} - 存在 ({size} bytes)")
        else:
            print(f"✗ {filename:30} - 不存在")


def main():
    """主测试函数"""
    print("\n")
    print("*" * 50)
    print("*" + " " * 12 + "算法验证平台 - 环境检测" + " " * 12 + "*")
    print("*" * 50)
    print()
    
    # 测试依赖包
    deps_ok = test_imports()
    
    # 测试模块
    modules_ok = test_modules()
    
    # 检查配置文件
    check_config_files()
    
    print("\n" + "=" * 50)
    print("检测结果总结")
    print("=" * 50)
    
    if deps_ok and modules_ok:
        print("✓ 所有检测通过！可以运行 algorithm_platform.py")
        print("\n启动命令: python algorithm_platform.py")
    else:
        print("✗ 检测发现问题，请先解决上述问题")
        
    print()


if __name__ == "__main__":
    main()
