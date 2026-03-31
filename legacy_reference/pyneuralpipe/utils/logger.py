"""
日志系统模块

为PyNeuralPipe应用提供统一的日志记录功能
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def setup_logger(
    name: str = "pyneuralpipe",
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，如果为None则不写入文件
        console_output: 是否输出到控制台
        
    Returns:
        配置好的日志记录器
    """
    
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除已有的处理器
    logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 添加控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 添加文件处理器
    if log_file:
        # 确保日志目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


class ProcessLogger:
    """
    处理过程日志记录器
    
    专门用于记录数据处理过程中的关键步骤和进度
    """
    
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logger = setup_logger(
            name=f"process_{self.session_id}",
            log_file=f"logs/process_{self.session_id}.log"
        )
        self.steps = []
        
    def start_step(self, step_name: str, description: str = ""):
        """开始一个处理步骤"""
        step_info = {
            'name': step_name,
            'description': description,
            'start_time': datetime.now(),
            'status': 'running'
        }
        self.steps.append(step_info)
        
        message = f"开始步骤: {step_name}"
        if description:
            message += f" - {description}"
        
        self.logger.info(message)
        return len(self.steps) - 1  # 返回步骤索引
    
    def complete_step(self, step_index: int, success: bool = True, message: str = ""):
        """完成一个处理步骤"""
        if 0 <= step_index < len(self.steps):
            step = self.steps[step_index]
            step['end_time'] = datetime.now()
            step['duration'] = step['end_time'] - step['start_time']
            step['status'] = 'completed' if success else 'failed'
            
            status_text = "完成" if success else "失败"
            log_message = f"步骤{status_text}: {step['name']} (耗时: {step['duration']})"
            if message:
                log_message += f" - {message}"
            
            if success:
                self.logger.info(log_message)
            else:
                self.logger.error(log_message)
    
    def log_progress(self, current: int, total: int, description: str = ""):
        """记录进度信息"""
        progress = (current / total) * 100 if total > 0 else 0
        message = f"进度: {current}/{total} ({progress:.1f}%)"
        if description:
            message += f" - {description}"
        self.logger.info(message)
    
    def log_parameters(self, params: dict, step_name: str = ""):
        """记录处理参数"""
        message = f"参数设置"
        if step_name:
            message += f" ({step_name})"
        message += ":\n"
        
        for key, value in params.items():
            message += f"  {key}: {value}\n"
        
        self.logger.info(message.rstrip())
    
    def log_results(self, results: dict, step_name: str = ""):
        """记录处理结果"""
        message = f"处理结果"
        if step_name:
            message += f" ({step_name})"
        message += ":\n"
        
        for key, value in results.items():
            message += f"  {key}: {value}\n"
        
        self.logger.info(message.rstrip())
    
    def log_info(self, message: str):
        """记录信息级别日志"""
        self.logger.info(message)
    
    def log_warning(self, message: str):
        """记录警告级别日志"""
        self.logger.warning(message)
    
    def log_error(self, message: str):
        """记录错误级别日志"""
        self.logger.error(message)
    
    def log_debug(self, message: str):
        """记录调试级别日志"""
        self.logger.debug(message)
    
    def get_summary(self) -> dict:
        """获取处理过程摘要"""
        completed_steps = [s for s in self.steps if s['status'] == 'completed']
        failed_steps = [s for s in self.steps if s['status'] == 'failed']
        running_steps = [s for s in self.steps if s['status'] == 'running']
        
        total_duration = sum([
            step.get('duration', datetime.now() - step['start_time'])
            for step in self.steps
        ], datetime.timedelta())
        
        return {
            'session_id': self.session_id,
            'total_steps': len(self.steps),
            'completed_steps': len(completed_steps),
            'failed_steps': len(failed_steps),
            'running_steps': len(running_steps),
            'total_duration': total_duration,
            'steps': self.steps.copy()
        }


# 创建默认日志记录器实例
default_logger = setup_logger()


def log_info(message: str):
    """记录信息级别日志"""
    default_logger.info(message)


def log_warning(message: str):
    """记录警告级别日志"""
    default_logger.warning(message)


def log_error(message: str):
    """记录错误级别日志"""
    default_logger.error(message)


def log_debug(message: str):
    """记录调试级别日志"""
    default_logger.debug(message)
