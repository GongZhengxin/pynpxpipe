"""
简单的配置文件编辑器GUI
用于查看和修改配置文件，并运行数据处理流程
"""
import sys
import yaml
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTextEdit, QPushButton, QFileDialog, QMessageBox,
    QLabel, QLineEdit, QSplitter, QGroupBox
)
from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtGui import QFont


class ConfigEditorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session_path = None
        self.session_nwb_config = None
        self.config_editors = {}
        self.process = None
        
        # 获取配置文件目录
        self.config_dir = Path(__file__).parent / "config"
        
        # 配置文件列表（排除 app.yaml 和 ui.yaml）
        self.config_files = [
            "nwbsession_template.yaml",
            "data_loader.yaml",
            "synchronizer.yaml",
            "spike_sorter.yaml",
            "quality_controller.yaml",
            "data_integrator.yaml"
        ]
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("PyNeuralPipe Config Editor")
        self.setGeometry(100, 100, 1200, 800)
        
        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Session 选择区域
        session_group = QGroupBox("Session Directory")
        session_layout = QHBoxLayout()
        session_group.setLayout(session_layout)
        
        self.session_path_label = QLabel("No session selected")
        self.session_path_label.setStyleSheet("padding: 5px;")
        session_layout.addWidget(self.session_path_label)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.select_session)
        session_layout.addWidget(browse_btn)
        
        main_layout.addWidget(session_group)
        
        # 创建分割器（上下分割）
        splitter = QSplitter(Qt.Vertical)
        
        # 上半部分：配置文件标签页
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        
        self.tab_widget = QTabWidget()
        config_layout.addWidget(self.tab_widget)
        
        # 为每个配置文件创建标签页
        for config_file in self.config_files:
            self.add_config_tab(config_file)
        
        # 保存和运行按钮
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Save Current Tab")
        save_btn.clicked.connect(self.save_current_config)
        button_layout.addWidget(save_btn)
        
        save_all_btn = QPushButton("Save All")
        save_all_btn.clicked.connect(self.save_all_configs)
        button_layout.addWidget(save_all_btn)
        
        button_layout.addStretch()
        
        self.run_btn = QPushButton("Run Process")
        self.run_btn.clicked.connect(self.run_process)
        self.run_btn.setEnabled(False)
        self.run_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }")
        button_layout.addWidget(self.run_btn)
        
        config_layout.addLayout(button_layout)
        splitter.addWidget(config_widget)
        
        # 下半部分：控制台输出
        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        
        console_label = QLabel("Process Console Output:")
        console_label.setStyleSheet("font-weight: bold;")
        console_layout.addWidget(console_label)
        
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setFont(QFont("Consolas", 9))
        self.console_output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        console_layout.addWidget(self.console_output)
        
        splitter.addWidget(console_widget)
        
        # 设置分割器比例
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(splitter)
        
    def add_config_tab(self, config_file):
        """添加配置文件标签页"""
        editor = QTextEdit()
        editor.setFont(QFont("Consolas", 10))
        
        # 读取配置文件
        config_path = self.config_dir / config_file
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                editor.setPlainText(f.read())
        
        # 使用更友好的标签名
        tab_name = config_file.replace('.yaml', '').replace('_', ' ').title()
        self.tab_widget.addTab(editor, tab_name)
        self.config_editors[config_file] = editor
        
    def select_session(self):
        """选择 session 文件夹"""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Session Directory", str(Path.home())
        )
        
        if directory:
            self.session_path = Path(directory)
            self.session_path_label.setText(str(self.session_path))
            self.run_btn.setEnabled(True)
            
            # 如果 session 文件夹中已有 nwbsession_template.yaml，加载它
            session_config = self.session_path / "nwbsession_template.yaml"
            if session_config.exists():
                with open(session_config, 'r', encoding='utf-8') as f:
                    self.config_editors["nwbsession_template.yaml"].setPlainText(f.read())
                self.console_output.append(f"✓ Loaded existing session config from {session_config}\n")
    
    def save_current_config(self):
        """保存当前标签页的配置"""
        current_index = self.tab_widget.currentIndex()
        config_file = self.config_files[current_index]
        
        self.save_config(config_file)
        
    def save_config(self, config_file):
        """保存指定的配置文件"""
        editor = self.config_editors[config_file]
        content = editor.toPlainText()
        
        # 验证 YAML 格式
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            QMessageBox.critical(self, "YAML Error", f"Invalid YAML format:\n{str(e)}")
            return False
        
        # 对于 nwbsession_template.yaml，保存到 session 文件夹
        if config_file == "nwbsession_template.yaml":
            if not self.session_path:
                QMessageBox.warning(self, "Warning", "Please select a session directory first!")
                return False
            
            save_path = self.session_path / config_file
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.console_output.append(f"✓ Saved {config_file} to session directory: {save_path}\n")
        else:
            # 其他配置文件保存到 config 目录
            save_path = self.config_dir / config_file
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.console_output.append(f"✓ Saved {config_file} to config directory: {save_path}\n")
        
        return True
        
    def save_all_configs(self):
        """保存所有配置文件"""
        all_saved = True
        for config_file in self.config_files:
            if not self.save_config(config_file):
                all_saved = False
        
        if all_saved:
            QMessageBox.information(self, "Success", "All configurations saved successfully!")
    
    def run_process(self):
        """运行数据处理脚本"""
        if not self.session_path:
            QMessageBox.warning(self, "Warning", "Please select a session directory first!")
            return
        
        # 保存所有配置
        self.save_all_configs()
        
        # 确认运行
        reply = QMessageBox.question(
            self, "Confirm", 
            f"Run processing pipeline on:\n{self.session_path}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 清空控制台
        self.console_output.clear()
        self.console_output.append(f"=== Starting Process ===\n")
        self.console_output.append(f"Session: {self.session_path}\n\n")
        
        # 创建进程
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)
        
        # 获取 Python 脚本路径
        script_path = Path(__file__).parent / "process_session.py"
        
        # 运行脚本
        self.run_btn.setEnabled(False)
        self.process.start(sys.executable, [str(script_path), str(self.session_path)])
        
    def handle_stdout(self):
        """处理标准输出"""
        data = self.process.readAllStandardOutput()
        stdout = bytes(data).decode("utf-8", errors="ignore")
        self.console_output.append(stdout)
        self.console_output.ensureCursorVisible()
        
    def handle_stderr(self):
        """处理标准错误"""
        data = self.process.readAllStandardError()
        stderr = bytes(data).decode("utf-8", errors="ignore")
        self.console_output.append(f'<span style="color: #f48771;">{stderr}</span>')
        self.console_output.ensureCursorVisible()
        
    def process_finished(self):
        """进程结束"""
        self.console_output.append("\n=== Process Finished ===\n")
        self.run_btn.setEnabled(True)
        
        exit_code = self.process.exitCode()
        if exit_code == 0:
            self.console_output.append("✓ Process completed successfully!\n")
            QMessageBox.information(self, "Success", "Processing completed successfully!")
        else:
            self.console_output.append(f"✗ Process failed with exit code {exit_code}\n")
            QMessageBox.warning(self, "Error", f"Processing failed with exit code {exit_code}")


def main():
    app = QApplication(sys.argv)
    window = ConfigEditorGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

