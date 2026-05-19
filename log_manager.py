# -*- coding: utf-8 -*-
"""
日志管理模块
功能：记录上位机程序的运行日志，包括操作记录、错误信息、调试信息等
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


class LogManager:
    """日志管理器 - 单例模式"""
    
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LogManager, cls).__new__(cls)
            cls._instance._setup_logger()
        return cls._instance
        
    def _setup_logger(self):
        """配置日志记录器"""
        # 创建logger
        self._logger = logging.getLogger('AlgorithmValidationPlatform')
        self._logger.setLevel(logging.DEBUG)
        
        # 避免重复添加handler
        if self._logger.handlers:
            return
            
        # 创建日志目录
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 日志文件名（按日期）
        log_date = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f"platform_{log_date}.log")
        
        # 文件处理器（详细日志，保存到文件）
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=30,  # 保留30天
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # 控制台处理器（只显示警告及以上级别）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        
        # 格式化器
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
        
        file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(console_formatter)
        
        # 添加处理器
        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)
        
    def get_logger(self):
        """获取logger实例"""
        return self._logger
        
    def debug(self, message):
        """调试信息"""
        self._logger.debug(message)
        
    def info(self, message):
        """普通信息"""
        self._logger.info(message)
        
    def warning(self, message):
        """警告信息"""
        self._logger.warning(message)
        
    def error(self, message, exc_info=False):
        """错误信息"""
        self._logger.error(message, exc_info=exc_info)
        
    def critical(self, message, exc_info=False):
        """严重错误"""
        self._logger.critical(message, exc_info=exc_info)
        
    def operation(self, operation_type, details=""):
        """记录用户操作"""
        message = f"[OPERATION] {operation_type}: {details}"
        self._logger.info(message)
        
    def device_action(self, action, device_ip, details=""):
        """记录设备操作"""
        message = f"[DEVICE] {action} on {device_ip}: {details}"
        self._logger.info(message)
        
    def performance_data(self, metrics):
        """记录性能数据"""
        message = f"[PERFORMANCE] NPU: {metrics.get('npu', 0)}%, CPU: {metrics.get('cpu', 0)}%, MEM: {metrics.get('memory', 0)}%"
        self._logger.debug(message)
        
    def export_log(self, export_path=None):
        """导出日志文件"""
        if export_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"platform_log_export_{timestamp}.log"
            
        try:
            log_dir = "logs"
            source_file = os.path.join(log_dir, f"platform_{datetime.now().strftime('%Y%m%d')}.log")
            
            if os.path.exists(source_file):
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                with open(export_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
                return True, f"日志已导出到: {export_path}"
            else:
                return False, "今日暂无日志记录"
                
        except Exception as e:
            return False, f"导出失败: {str(e)}"
            
    def cleanup_old_logs(self, days=30):
        """清理旧日志文件"""
        try:
            log_dir = "logs"
            if not os.path.exists(log_dir):
                return
                
            cutoff_date = datetime.now().timestamp() - (days * 24 * 3600)
            
            for filename in os.listdir(log_dir):
                if filename.startswith("platform_") and filename.endswith(".log"):
                    filepath = os.path.join(log_dir, filename)
                    if os.path.getmtime(filepath) < cutoff_date:
                        os.remove(filepath)
                        
            self.info(f"已清理{days}天前的日志文件")
            
        except Exception as e:
            self.error(f"清理日志失败: {str(e)}")


# 全局日志管理器实例
log_manager = LogManager()
logger = log_manager.get_logger()


# 便捷函数（可以直接导入使用）
def log_debug(message):
    log_manager.debug(message)

def log_info(message):
    log_manager.info(message)

def log_warning(message):
    log_manager.warning(message)

def log_error(message):
    log_manager.error(message)

def log_operation(operation_type, details=""):
    log_manager.operation(operation_type, details)

def log_device_action(action, device_ip, details=""):
    log_manager.device_action(action, device_ip, details)
