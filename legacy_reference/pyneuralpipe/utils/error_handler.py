"""
错误处理模块

提供统一的错误处理和异常管理功能
"""

import traceback
import functools
from typing import Callable, Any, Optional, Type, Union
from enum import Enum
import streamlit as st
from .logger import default_logger


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"        # 轻微错误，不影响主要功能
    MEDIUM = "medium"  # 中等错误，影响部分功能
    HIGH = "high"      # 严重错误，影响主要功能
    CRITICAL = "critical"  # 致命错误，导致程序无法继续


class PyNeuralPipeError(Exception):
    """PyNeuralPipe基础异常类"""
    
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.MEDIUM, 
                 details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.details = details or {}


class DataLoadError(PyNeuralPipeError):
    """数据加载错误"""
    pass


class ProcessingError(PyNeuralPipeError):
    """数据处理错误"""
    pass


class ConfigurationError(PyNeuralPipeError):
    """配置错误"""
    pass


class ValidationError(PyNeuralPipeError):
    """数据验证错误"""
    pass


class FileIOError(PyNeuralPipeError):
    """文件I/O错误"""
    pass


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self, logger=None):
        self.logger = logger or default_logger
        self.error_history = []
    
    def handle_error(self, error: Exception, context: str = "", 
                    show_to_user: bool = True) -> bool:
        """
        处理错误
        
        Args:
            error: 异常对象
            context: 错误上下文信息
            show_to_user: 是否在UI中显示错误
            
        Returns:
            是否应该继续执行程序
        """
        # 记录错误
        error_info = {
            'type': type(error).__name__,
            'message': str(error),
            'context': context,
            'traceback': traceback.format_exc()
        }
        
        if isinstance(error, PyNeuralPipeError):
            error_info['severity'] = error.severity.value
            error_info['details'] = error.details
        else:
            error_info['severity'] = ErrorSeverity.MEDIUM.value
        
        self.error_history.append(error_info)
        
        # 记录到日志
        self._log_error(error_info)
        
        # 在UI中显示错误
        if show_to_user:
            self._show_error_to_user(error_info)
        
        # 根据错误严重程度决定是否继续
        severity = ErrorSeverity(error_info['severity'])
        return severity not in [ErrorSeverity.CRITICAL]
    
    def _log_error(self, error_info: dict):
        """记录错误到日志"""
        severity = error_info['severity']
        message = f"[{severity.upper()}] {error_info['type']}: {error_info['message']}"
        
        if error_info['context']:
            message += f" (Context: {error_info['context']})"
        
        if severity == ErrorSeverity.CRITICAL.value:
            self.logger.critical(message)
            self.logger.critical(f"Traceback:\n{error_info['traceback']}")
        elif severity == ErrorSeverity.HIGH.value:
            self.logger.error(message)
            self.logger.debug(f"Traceback:\n{error_info['traceback']}")
        elif severity == ErrorSeverity.MEDIUM.value:
            self.logger.warning(message)
        else:
            self.logger.info(message)
    
    def _show_error_to_user(self, error_info: dict):
        """在Streamlit界面中显示错误"""
        severity = error_info['severity']
        message = error_info['message']
        context = error_info['context']
        
        # 构建显示消息
        display_message = message
        if context:
            display_message = f"{context}: {message}"
        
        # 根据严重程度选择显示方式
        if severity == ErrorSeverity.CRITICAL.value:
            st.error(f"🚨 致命错误: {display_message}")
            st.stop()  # 停止应用执行
        elif severity == ErrorSeverity.HIGH.value:
            st.error(f"❌ 严重错误: {display_message}")
        elif severity == ErrorSeverity.MEDIUM.value:
            st.warning(f"⚠️ 警告: {display_message}")
        else:
            st.info(f"ℹ️ 信息: {display_message}")
    
    def get_error_summary(self) -> dict:
        """获取错误摘要"""
        if not self.error_history:
            return {'total_errors': 0, 'by_severity': {}, 'recent_errors': []}
        
        by_severity = {}
        for error in self.error_history:
            severity = error['severity']
            by_severity[severity] = by_severity.get(severity, 0) + 1
        
        return {
            'total_errors': len(self.error_history),
            'by_severity': by_severity,
            'recent_errors': self.error_history[-10:]  # 最近10个错误
        }
    
    def clear_error_history(self):
        """清除错误历史"""
        self.error_history.clear()


# 全局错误处理器实例
_error_handler = ErrorHandler()


def handle_error(error: Exception, context: str = "", show_to_user: bool = True) -> bool:
    """处理错误的便捷函数"""
    return _error_handler.handle_error(error, context, show_to_user)


def safe_execute(func: Callable, *args, context: str = "", 
                show_errors: bool = True, **kwargs) -> tuple[bool, Any]:
    """
    安全执行函数
    
    Args:
        func: 要执行的函数
        *args: 函数参数
        context: 执行上下文
        show_errors: 是否显示错误
        **kwargs: 函数关键字参数
        
    Returns:
        (success, result) 元组
    """
    try:
        result = func(*args, **kwargs)
        return True, result
    except Exception as e:
        handle_error(e, context, show_errors)
        return False, None


def error_boundary(context: str = "", severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                  show_to_user: bool = True):
    """
    错误边界装饰器
    
    Args:
        context: 错误上下文
        severity: 默认错误严重程度
        show_to_user: 是否向用户显示错误
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except PyNeuralPipeError:
                # 重新抛出自定义异常
                raise
            except Exception as e:
                # 将其他异常包装为自定义异常
                wrapped_error = PyNeuralPipeError(
                    message=str(e),
                    severity=severity,
                    details={'original_error': type(e).__name__}
                )
                handle_error(wrapped_error, context or func.__name__, show_to_user)
                raise wrapped_error
        return wrapper
    return decorator


def validate_data(data: Any, validator: Callable[[Any], bool], 
                 error_message: str, context: str = "") -> bool:
    """
    数据验证函数
    
    Args:
        data: 要验证的数据
        validator: 验证函数
        error_message: 验证失败时的错误消息
        context: 验证上下文
        
    Returns:
        验证是否通过
    """
    try:
        if not validator(data):
            raise ValidationError(error_message, ErrorSeverity.MEDIUM)
        return True
    except Exception as e:
        handle_error(e, context)
        return False


def create_progress_callback(total_steps: int, description: str = "处理中..."):
    """
    创建进度回调函数，用于长时间运行的操作
    
    Args:
        total_steps: 总步骤数
        description: 进度描述
        
    Returns:
        进度回调函数
    """
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(current_step: int, step_description: str = ""):
        progress = current_step / total_steps
        progress_bar.progress(progress)
        
        status = f"{description} ({current_step}/{total_steps})"
        if step_description:
            status += f" - {step_description}"
        
        status_text.text(status)
        
        if current_step >= total_steps:
            progress_bar.empty()
            status_text.empty()
    
    return update_progress
