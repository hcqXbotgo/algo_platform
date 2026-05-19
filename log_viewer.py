# -*- coding: utf-8 -*-
"""
日志查看器 - 用于在上位机界面中查看运行日志
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QFileDialog, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from datetime import datetime
import os


class LogViewerDialog(QDialog):
    """日志查看器对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行日志查看器")
        self.setGeometry(200, 200, 1000, 700)
        
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setFont(QFont("Consolas", 9))
        
        self.setup_ui()
        self.load_today_log()
        
    def setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("📋 算法验证平台 - 运行日志")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title_label)
        
        # 日志显示区
        log_group = QGroupBox("日志内容")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_text_edit)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # 按钮区
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.load_today_log)
        btn_layout.addWidget(refresh_btn)
        
        export_btn = QPushButton("💾 导出日志")
        export_btn.clicked.connect(self.export_log)
        btn_layout.addWidget(export_btn)
        
        clear_btn = QPushButton("🗑️ 清空显示")
        clear_btn.clicked.connect(self.clear_display)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
    def load_today_log(self):
        """加载今天的日志"""
        try:
            log_dir = "logs"
            today = datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(log_dir, f"platform_{today}.log")
            
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.log_text_edit.setText(content)
                
                # 滚动到底部
                scrollbar = self.log_text_edit.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            else:
                self.log_text_edit.setText("今日暂无日志记录")
                
        except Exception as e:
            self.log_text_edit.setText(f"加载日志失败: {str(e)}")
            
    def export_log(self):
        """导出日志"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"platform_log_{timestamp}.log"
            
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                "导出日志文件",
                default_name,
                "Log Files (*.log);;Text Files (*.txt)"
            )
            
            if file_name:
                content = self.log_text_edit.toPlainText()
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
                QMessageBox.information(self, "成功", f"日志已导出到:\n{file_name}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
            
    def clear_display(self):
        """清空显示（不影响实际日志文件）"""
        self.log_text_edit.clear()
        
    def append_log(self, text):
        """追加日志内容"""
        self.log_text_edit.append(text)
