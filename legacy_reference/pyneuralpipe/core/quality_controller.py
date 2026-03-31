"""
质量控制模块

负责对尖峰排序结果进行质量评估和神经元分类
集成Bombcell Python API实现高质量的神经元质量控制
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
import warnings
import json

# Bombcell Python API
try:
    import bombcell as bc
    BOMBCELL_AVAILABLE = True
except ImportError:
    BOMBCELL_AVAILABLE = False
    warnings.warn("Bombcell not available. Please install with: pip install bombcell")

from utils.logger import ProcessLogger
from utils.error_handler import ProcessingError, error_boundary
from utils.config_manager import get_config_manager


class QualityController:
    """
    质量控制器类
    
    集成Bombcell Python API实现高质量的神经元质量控制
    基于开发计划重构，提供完整的qMetric和unitType功能
    """
    
    def __init__(self, kilosort_output_path, imec_data_path=None):
        """
        初始化质量控制器
        
        Args:
            kilosort_output_path: Kilosort输出目录路径
            imec_data_path: 原始数据路径(可选，用于更精确的质量评估)
        """
        self.ks_output_path = Path(kilosort_output_path)
        self.imec_data_path = Path(imec_data_path) if imec_data_path else None
        self.logger = ProcessLogger()
        
        # 获取配置管理器和配置
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_quality_controller_config()
        
        # Bombcell核心结果
        self.bombcell_params = None
        self.qMetric = None          # Bombcell质量指标字典
        self.unitType = None         # Bombcell单元类型数组 (1=good, 2=mua, 3=no-somatic, 0=noise)
        self.unit_type_strings = None # 单元类型字符串描述
        self.figures = None          # Bombcell生成的图表
        
        # 处理结果缓存
        self.bombcell_results = None
        self.save_path = None
        
        # 检查环境和输入
        self._check_bombcell_availability()
        self._validate_kilosort_output()
    
    def _check_bombcell_availability(self):
        """检查Bombcell可用性"""
        if not BOMBCELL_AVAILABLE:
            raise ProcessingError(
                "Bombcell Python API不可用。请在spikesort环境中安装: pip install bombcell"
            )
        self.logger.log_info("Bombcell Python API已就绪")
    
    def _validate_kilosort_output(self):
        """验证Kilosort输出目录"""
        self.logger.log_info(f"验证Kilosort输出目录: {self.ks_output_path}")
        if not self.ks_output_path.exists():
            raise ProcessingError(f"Kilosort输出目录不存在: {self.ks_output_path}")
        
        required_files = [
            'spike_times.npy', 'spike_clusters.npy', 'cluster_info.tsv',
            'templates.npy', 'whitening_mat.npy', 'channel_map.npy'
        ]
        
        missing_files = []
        for file_name in required_files:
            file_path = self.ks_output_path / file_name
            if not file_path.exists():
                missing_files.append(file_name)
        
        if missing_files:
            self.logger.log_warning(f"部分Kilosort文件缺失: {missing_files}")
            # 仅检查必需的最基本文件
            essential_files = ['spike_times.npy', 'spike_clusters.npy']
            essential_missing = [f for f in essential_files if f in missing_files]
            if essential_missing:
                raise ProcessingError(f"Kilosort输出目录缺少关键文件: {essential_missing}")
       
    def _setup_save_directory(self):
        """设置Bombcell保存目录"""
        self.save_path = self.ks_output_path.parent.parent/ "bombcell"
        self.save_path.mkdir(exist_ok=True, parents=True)
        self.logger.log_info(f"Bombcell结果保存路径: {self.save_path}")
        return self.save_path
    
    def setup_bombcell_params(self):
        """
        设置Bombcell参数 - 完全使用bc.get_default_parameters
        """
        step_idx = self.logger.start_step("setup_bombcell_params", "设置Bombcell参数")
        
        try:
            if self.imec_data_path is None:
                ap_file = None
                meta_file = None
                self.logger.log_info(f"未找到ap.bin和ap.meta文件")
            else:
                ap_file = list(self.imec_data_path.glob("*.ap.bin"))
                meta_file = list(self.imec_data_path.glob("*.ap.meta"))
                if len(ap_file) == 0 or len(meta_file) == 0:
                    raise ProcessingError(f"{self.imec_data_path}未找到ap.bin或ap.meta文件")
                elif len(ap_file) > 1 or len(meta_file) > 1:
                    raise ProcessingError(f"{self.imec_data_path}找到多个ap.bin或ap.meta文件")
                ap_file = ap_file[0]
                meta_file = meta_file[0]
                self.logger.log_info(f"找到ap.bin和ap.meta文件: {ap_file}和{meta_file}")
               
            # 获取Bombcell默认参数 - 不使用任何自定义参数
            self.bombcell_params = bc.get_default_parameters(
                str(self.ks_output_path),
                raw_file=str(ap_file) if ap_file else None,
                meta_file=str(meta_file) if meta_file else None,
                kilosort_version=4
            )
            
            self.logger.log_info("使用Bombcell默认参数")
            self.bombcell_params['tauR_valuesMin'] = 1.5 / 1000
            self.bombcell_params['tauR_valuesStep'] = 0.1 / 1000
            self.bombcell_params['tauR_valuesMax'] = 2.4 / 1000
            self.logger.complete_step(step_idx, True, "Bombcell参数设置完成")
            
            return self.bombcell_params
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"设置Bombcell参数失败: {str(e)}")
    
    @error_boundary("Bombcell质量控制")
    def run_quality_control(self, save_figures=True):
        """
        运行Bombcell质量控制
        
        Args:
            save_figures: 是否保存质量控制图表
            
        Returns:
            dict: 包含qMetric, unitType和figures的结果字典
        """
        step_idx = self.logger.start_step("run_quality_control", "运行Bombcell质量控制")
        
        try:
            # 确保参数已设置
            if self.bombcell_params is None:
                self.setup_bombcell_params()
            
            # 设置保存路径
            self._setup_save_directory()
            
            self.logger.log_info(f"运行Bombcell分析，保存路径: {self.save_path}")
            
            # 运行Bombcell - 根据开发计划的标准实现
            self.logger.log_info("开始Bombcell分析...")
            
            (self.qMetric, 
             self.bombcell_params, 
             self.unitType, 
             self.unit_type_strings, 
             self.figures) = bc.run_bombcell(
                str(self.ks_output_path), 
                str(self.save_path), 
                self.bombcell_params,
                return_figures=save_figures
            )
            
            # 缓存完整结果
            self.bombcell_results = {
                'qMetric': self.qMetric,
                'unitType': self.unitType,
                'unit_type_strings': self.unit_type_strings,
                'figures': self.figures if save_figures else None,
                'params': self.bombcell_params.copy()
            }
            
            # 统计分析结果
            results_summary = self._generate_bombcell_summary()
            
            # 保存结果到文件
            self._save_bombcell_results()
            
            self.logger.log_results(results_summary, "Bombcell质量控制结果")
            self.logger.complete_step(
                step_idx, True, 
                f"Bombcell分析完成：{results_summary['good_units']}/{results_summary['total_units']} 个优质神经元"
            )
            
            return self.bombcell_results.copy()
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"Bombcell质量控制失败: {str(e)}")
    
    def _generate_bombcell_summary(self):
        """生成Bombcell结果摘要"""
        if self.unitType is None:
            return {}
        
        num_units = len(self.unitType)
        good_units = np.sum(self.unitType == 1)
        mua_units = np.sum(self.unitType == 2)
        no_somatic_units = np.sum(self.unitType == 3)
        noise_units = np.sum(self.unitType == 0)
        
        # 分析qMetric指标分布
        qmetric_summary = {}
        if self.qMetric:
            for metric_name, values in self.qMetric.items():
                if isinstance(values, (list, np.ndarray)) and len(values) > 0:
                    values_array = np.array(values)
                    qmetric_summary[metric_name] = {
                        'mean': float(np.nanmean(values_array)),
                        'std': float(np.nanstd(values_array)),
                        'median': float(np.nanmedian(values_array))
                    }
        
        summary = {
            'total_units': int(num_units),
            'good_units': int(good_units),
            'mua_units': int(mua_units),
            'no-somatic_units': int(no_somatic_units),
            'noise_units': int(noise_units),
            'good_unit_ratio': float(1 - noise_units / num_units) if num_units > 0 else 0.0,
            'qMetric_summary': qmetric_summary
        }
        
        return summary
    
    def _save_bombcell_results(self):
        """保存Bombcell结果到JSON文件"""
        if not self.bombcell_results or not self.save_path:
            return
        
        try:
            # 准备可序列化的结果
            serializable_results = {}
            for key, value in self.bombcell_results.items():
                if key == 'figures':
                    # 图表对象不序列化，只记录是否存在
                    serializable_results[key] = f"{len(value)} figures" if value else None
                elif isinstance(value, np.ndarray):
                    serializable_results[key] = value.tolist()
                elif isinstance(value, dict):
                    serializable_dict = {}
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, np.ndarray):
                            serializable_dict[sub_key] = sub_value.tolist()
                        else:
                            serializable_dict[sub_key] = sub_value
                    serializable_results[key] = serializable_dict
                else:
                    serializable_results[key] = value
            
            # 保存到JSON文件
            results_file = self.save_path / "bombcell_results.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_results, f, indent=2, ensure_ascii=False)
            
            self.logger.log_info(f"Bombcell结果已保存到: {results_file}")
            
        except Exception as e:
            self.logger.log_warning(f"保存Bombcell结果时出错: {str(e)}")
    
    # 新增核心接口方法 - 根据开发计划设计
    
    def get_good_units(self):
        """
        获取优质神经元列表（unitType == 1）
        
        Returns:
            list: 优质神经元索引列表
        """
        if self.unitType is None:
            return []
        
        good_indices = np.where(self.unitType >= 1)[0]
        return good_indices.tolist()
    
    def get_unit_quality_metrics(self, unit_indices=None):
        """
        获取指定神经元的质量指标
        
        Args:
            unit_indices: 神经元索引列表，如果为None则返回所有
            
        Returns:
            dict: 神经元质量指标字典
        """
        if self.qMetric is None:
            return {}
        
        if unit_indices is None:
            return self.qMetric.copy()
        
        filtered_metrics = {}
        for metric_name, values in self.qMetric.items():
            if isinstance(values, (list, np.ndarray)):
                filtered_values = [values[i] for i in unit_indices if i < len(values)]
                filtered_metrics[metric_name] = filtered_values
            else:
                filtered_metrics[metric_name] = values
        
        return filtered_metrics
    
    def get_unit_classifications(self):
        """
        获取神经元分类结果
        
        Returns:
            dict: 包含分类和统计信息的字典
        """
        if self.unitType is None:
            return {}
        
        classifications = {}
        for i, unit_type in enumerate(self.unitType):
            if unit_type == 1:
                classifications[i] = 'good'
            elif unit_type == 2:
                classifications[i] = 'mua'
            elif unit_type == 3:
                classifications[i] = 'no-somatic'
            elif unit_type == 0:
                classifications[i] = 'noise'
            else:
                classifications[i] = 'unknown'
        
        # 统计信息
        good_count = np.sum(self.unitType == 1)
        mua_count = np.sum(self.unitType == 2)
        no_somatic_count = np.sum(self.unitType == 3)
        mua_noise_count = np.sum(self.unitType == 0)
        
        return {
            'classifications': classifications,
            'counts': {
                'good': int(good_count),
                'mua': int(mua_count),
                'no-somatic': int(no_somatic_count),
                'noise': int(mua_noise_count),
                'total': len(self.unitType)
            },
            'good_unit_ratio': float(good_count / len(self.unitType))
        }
    
    def filter_units_by_criteria(self, custom_criteria):
        """
        根据自定义标准进一步筛选神经元
        
        Args:
            custom_criteria: 自定义筛选标准字典
            
        Returns:
            list: 满足条件的神经元索引列表
        """
        if self.qMetric is None or self.unitType is None:
            return []
        
        # 先获取Bombcell认为的good units
        good_units = self.get_good_units()
        
        if not custom_criteria:
            return good_units
        
        # 应用自定义筛选标准
        filtered_units = []
        for unit_idx in good_units:
            meets_criteria = True
            
            for metric_name, criterion in custom_criteria.items():
                if metric_name in self.qMetric:
                    metric_values = self.qMetric[metric_name]
                    if isinstance(metric_values, (list, np.ndarray)) and unit_idx < len(metric_values):
                        value = metric_values[unit_idx]
                        
                        # 检查阈值
                        if isinstance(criterion, dict):
                            if 'min' in criterion and value < criterion['min']:
                                meets_criteria = False
                                break
                            if 'max' in criterion and value > criterion['max']:
                                meets_criteria = False
                                break
                        else:
                            # 简单阈值检查
                            if value < criterion:
                                meets_criteria = False
                                break
            
            if meets_criteria:
                filtered_units.append(unit_idx)
        
        return filtered_units
    
    def export_quality_results(self, output_path):
        """
        导出质量控制结果到文件
        
        Args:
            output_path: 导出文件路径
        """
        if not self.bombcell_results:
            raise ProcessingError("没有可导出的Bombcell结果")
        
        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 准备导出数据
            export_data = {
                'summary': self._generate_bombcell_summary(),
                'unit_classifications': self.get_unit_classifications(),
                'good_units': self.get_good_units(),
                'qMetric': self.qMetric,
                'unitType': self.unitType.tolist() if self.unitType is not None else None,
                'unit_type_strings': self.unit_type_strings.tolist() if self.unit_type_strings is not None else None,
                'bombcell_params': self.bombcell_params
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.log_info(f"质量控制结果已导出到: {output_file}")
            
        except Exception as e:
            raise ProcessingError(f"导出质量控制结果失败: {str(e)}")
    
    # 保留兼容性接口
    
    def calculate_metrics(self) -> bool:
        """计算质量评估指标 (兼容性接口)"""
        try:
            self.run_quality_control()
            return True
        except Exception:
            return False
    
    def get_bombcell_figures(self):
        """获取Bombcell生成的质量控制图表"""
        return self.figures
    
    def get_quality_metrics_df(self):
        """获取质量指标的DataFrame格式"""
        if self.qMetric is None:
            return None
        
        # 转换为DataFrame
        df = pd.DataFrame(self.qMetric)
        
        # 添加unitType列
        df.insert(0, 'unitType', self.unitType)
        df.insert(1, 'unit_type_strings', self.unit_type_strings)
        return df
    
    def get_bombcell_parameters(self):
        """获取当前使用的Bombcell参数"""
        return self.bombcell_params.copy() if self.bombcell_params else None
    
    
    def classify_units(self) -> bool:
        """对神经元进行分类 (兼容性接口)"""
        try:
            self.run_quality_control()
            return True
        except Exception:
            return False
