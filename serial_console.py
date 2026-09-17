# -*- coding: utf-8 -*-
"""Qt serial console backed by SerialManager."""

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SerialConsoleDialog(QDialog):
    def __init__(self, serial_manager, preferred_port="", preferred_baud=115200, parent=None):
        super().__init__(parent)
        self.serial_manager = serial_manager
        self.preferred_port = preferred_port
        self.preferred_baud = int(preferred_baud or 115200)
        self.setWindowTitle("设备串口终端")
        self.resize(820, 560)

        root = QVBoxLayout(self)
        form = QFormLayout()

        port_row = QWidget()
        port_layout = QHBoxLayout(port_row)
        port_layout.setContentsMargins(0, 0, 0, 0)
        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_ports)
        port_layout.addWidget(self.port_combo, 1)
        port_layout.addWidget(self.refresh_button)
        form.addRow("串口:", port_row)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(["115200", "921600", "460800", "230400", "57600"])
        self.baud_combo.setCurrentText(str(self.preferred_baud))
        form.addRow("波特率:", self.baud_combo)

        connection_row = QWidget()
        connection_layout = QHBoxLayout(connection_row)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.status_label = QLabel("未连接")
        connection_layout.addWidget(self.connect_button)
        connection_layout.addWidget(self.status_label, 1)
        form.addRow("状态:", connection_row)
        root.addLayout(form)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        root.addWidget(self.output, 1)

        command_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("输入串口命令")
        self.command_input.returnPressed.connect(self.send_command)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_command)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.output.clear)
        command_row.addWidget(self.command_input, 1)
        command_row.addWidget(self.send_button)
        command_row.addWidget(self.clear_button)
        root.addLayout(command_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.read_timer = QTimer(self)
        self.read_timer.setInterval(50)
        self.read_timer.timeout.connect(self.poll_serial)
        self.read_timer.start()

        self.refresh_ports()
        self.update_connection_state()

    def refresh_ports(self):
        selected = self.serial_manager.port or self.preferred_port or self.port_combo.currentData()
        self.port_combo.clear()
        for port in self.serial_manager.available_ports():
            label = port.device
            if port.description and port.description != "n/a":
                label += f" - {port.description}"
            self.port_combo.addItem(label, port.device)
        if selected:
            index = self.port_combo.findData(selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def toggle_connection(self):
        if self.serial_manager.is_connected:
            self.serial_manager.disconnect()
            self.update_connection_state()
            return

        port = self.port_combo.currentData()
        try:
            baudrate = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "串口", "波特率必须是整数")
            return
        success, message = self.serial_manager.connect(port, baudrate)
        if not success:
            QMessageBox.critical(self, "串口连接失败", message)
        else:
            self.append_output(f"\n[{message}]\n")
            self.serial_manager.send(self.serial_manager.line_ending)
        self.update_connection_state()

    def update_connection_state(self):
        connected = self.serial_manager.is_connected
        self.connect_button.setText("断开" if connected else "连接")
        self.send_button.setEnabled(connected)
        self.command_input.setEnabled(connected)
        if connected:
            self.status_label.setText(
                f"已连接 {self.serial_manager.port} @ {self.serial_manager.baudrate} 8N1"
            )
            index = self.port_combo.findData(self.serial_manager.port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            self.baud_combo.setCurrentText(str(self.serial_manager.baudrate))
        else:
            self.status_label.setText("未连接")

    def append_output(self, text):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def poll_serial(self):
        try:
            data = self.serial_manager.read_available()
            if data:
                self.append_output(data)
        except Exception as exc:
            self.append_output(f"\n[串口读取失败: {exc}]\n")
            self.serial_manager.disconnect()
            self.update_connection_state()

    def send_command(self):
        command = self.command_input.text()
        if not command.strip():
            return
        success, message = self.serial_manager.send_command(command)
        if not success:
            QMessageBox.warning(self, "串口发送失败", message)
            self.update_connection_state()
            return
        self.command_input.clear()

    def closeEvent(self, event):
        self.read_timer.stop()
        super().closeEvent(event)
