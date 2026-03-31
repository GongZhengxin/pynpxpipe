"""
配置管理模块

重构后的配置管理器，支持分布式YAML配置文件，确保配置文件是所有参数的唯一来源
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union
import os


class ConfigManager:
    """
    重构后的配置管理器
    
    特性：
    1. 支持多个分布式YAML配置文件
    2. YAML文件是所有默认值的唯一来源
    3. 简化的API，直接返回配置字典
    4. 自动文件监控和重载（可选）
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置文件目录，默认为 config/
        """
        self.config_dir = Path(config_dir or "config")
        
        # 配置文件映射
        self.config_files = {
            # 'app': Path(__file__).parent.parent / 'config' / 'app.yaml',
            'data_loader': Path(__file__).parent.parent / 'config' / 'data_loader.yaml',
            'synchronizer': Path(__file__).parent.parent / 'config' / 'synchronizer.yaml', 
            'spike_sorter': Path(__file__).parent.parent / 'config' / 'spike_sorter.yaml',
            'quality_controller': Path(__file__).parent.parent / 'config' / 'quality_controller.yaml',
            'data_integrator': Path(__file__).parent.parent / 'config' / 'data_integrator.yaml',
            # 'ui': Path(__file__).parent.parent / 'config' / 'ui.yaml'
        }
        
        # 缓存的配置数据
        self._configs = {}
        
        # 加载所有配置
        self._load_all_configs()
    
    def _load_all_configs(self):
        """加载所有配置文件"""
        for module_name, filename in self.config_files.items():
            self._load_config(module_name, filename)
    
    def _load_config(self, module_name: str, filename: str):
        """
        加载单个配置文件
        
        Args:
            module_name: 模块名称
            filename: 配置文件名
        """
        config_path = self.config_dir / filename
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f) or {}
                self._configs[module_name] = config_data
                
            except Exception as e:
                print(f"加载配置文件 {filename} 失败: {e}")
                self._configs[module_name] = {}
        else:
            print(f"配置文件 {filename} 不存在，使用空配置")
            self._configs[module_name] = {}
    
    def get_config(self, module_name: str) -> Dict[str, Any]:
        """
        获取指定模块的配置
        
        Args:
            module_name: 模块名称 ('app', 'data_loader', 'synchronizer', 等)
            
        Returns:
            配置字典
        """
        return self._configs.get(module_name, {})
    
    def get_app_config(self) -> Dict[str, Any]:
        """获取应用配置"""
        return self.get_config('app')
    
    def get_data_loader_config(self) -> Dict[str, Any]:
        """获取数据加载器配置"""
        return self.get_config('data_loader')
    
    def get_synchronizer_config(self) -> Dict[str, Any]:
        """获取同步器配置"""
        return self.get_config('synchronizer')
    
    def get_spike_sorter_config(self) -> Dict[str, Any]:
        """获取尖峰排序器配置"""
        return self.get_config('spike_sorter')
    
    def get_quality_controller_config(self) -> Dict[str, Any]:
        """获取质量控制器配置"""
        return self.get_config('quality_controller')
    
    def get_data_integrator_config(self) -> Dict[str, Any]:
        """获取数据整合器配置"""
        return self.get_config('data_integrator')
    
    def get_ui_config(self) -> Dict[str, Any]:
        """获取UI配置"""
        return self.get_config('ui')
    
    # SpikeInterface Pipeline 专用方法
    def get_spike_sorting_pipeline_config(self) -> Dict[str, Any]:
        """获取SpikeInterface Pipeline配置"""
        spike_sorter_config = self.get_spike_sorter_config()
        return spike_sorter_config.get('spike_sorting_pipeline', {})
    
    def get_preprocessing_protocol(self) -> Dict[str, Any]:
        """获取预处理协议"""
        pipeline_config = self.get_spike_sorting_pipeline_config()
        return pipeline_config.get('preprocessing', {})
    
    def get_sorting_protocol(self) -> Dict[str, Any]:
        """获取排序协议"""
        pipeline_config = self.get_spike_sorting_pipeline_config()
        return pipeline_config.get('sorting', {})
    
    def get_postprocessing_protocol(self) -> Dict[str, Any]:
        """获取后处理协议"""
        pipeline_config = self.get_spike_sorting_pipeline_config()
        return pipeline_config.get('postprocessing', {})
    
    def get_job_kwargs(self) -> Dict[str, Any]:
        """获取作业参数"""
        pipeline_config = self.get_spike_sorting_pipeline_config()
        return pipeline_config.get('job_kwargs', {})

    # 向后兼容的Kilosort配置
    def get_kilosort_config(self) -> Dict[str, Any]:
        """获取向后兼容的Kilosort配置"""
        spike_sorter_config = self.get_spike_sorter_config()
        return spike_sorter_config.get('kilosort', {})
    
    def update_config(self, module_name: str, config_path: str, value: Any):
        """
        更新配置值（运行时）
        
        Args:
            module_name: 模块名称
            config_path: 配置路径，支持点分隔的嵌套路径，如 'preprocessing.highpass_filter.freq_min'
            value: 新值
        """
        config = self._configs.get(module_name, {})
        
        # 解析嵌套路径
        keys = config_path.split('.')
        current = config
        
        # 导航到目标位置
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        # 设置值
        current[keys[-1]] = value
        
        # 可选：保存到文件
        # self._save_config(module_name)
    
    def update_section_config(self, module_name: str, section_path: str, new_config: Dict[str, Any]):
        """
        更新整个配置节
        
        Args:
            module_name: 模块名称
            section_path: 节路径，如 'spike_sorting_pipeline.preprocessing'
            new_config: 新的配置字典
        """
        config = self._configs.get(module_name, {})
        
        if '.' in section_path:
            keys = section_path.split('.')
            current = config
            
            # 导航到目标位置
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            # 更新节
            current[keys[-1]] = new_config
        else:
            config[section_path] = new_config
    
    def reload_config(self, module_name: Optional[str] = None):
        """
        重新加载配置文件
        
        Args:
            module_name: 指定模块名称，None表示重载所有配置
        """
        if module_name is None:
            self._load_all_configs()
        elif module_name in self.config_files:
            self._load_config(module_name, self.config_files[module_name])
    
    def _save_config(self, module_name: str):
        """
        保存配置到文件（可选功能）
        
        Args:
            module_name: 模块名称
        """
        if module_name not in self.config_files:
            return
        
        config_path = self.config_dir / self.config_files[module_name]
        config_data = self._configs.get(module_name, {})
        
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, 
                         allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"保存配置文件 {config_path} 失败: {e}")
    
    def ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置（用于调试）"""
        return self._configs.copy()
    
    # 便利方法：获取常用配置项
    def get_paths_config(self) -> Dict[str, str]:
        """获取路径配置"""
        app_config = self.get_app_config()
        return app_config.get('paths', {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        app_config = self.get_app_config()
        return app_config.get('logging', {})
    
    def get_performance_config(self) -> Dict[str, Any]:
        """获取性能配置"""
        app_config = self.get_app_config()
        return app_config.get('performance', {})


# 全局配置管理器实例
_config_manager = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config(module_name: str) -> Dict[str, Any]:
    """
    快捷方式：获取指定模块配置
    
    Args:
        module_name: 模块名称
        
    Returns:
        配置字典
    """
    return get_config_manager().get_config(module_name)


def update_config(module_name: str, config_path: str, value: Any):
    """
    快捷方式：更新配置值
    
    Args:
        module_name: 模块名称
        config_path: 配置路径
        value: 新值
    """
    get_config_manager().update_config(module_name, config_path, value)