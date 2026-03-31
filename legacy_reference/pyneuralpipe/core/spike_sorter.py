"""
尖峰排序模块

使用Kilosort4进行尖峰排序，复现for_sorter.md的处理流程

支持两种初始化方式：
1. 直接传入SpikeInterface Recording对象（从DataLoader获得）
2. 传入SpikeGLX数据文件夹路径（独立使用）

使用示例：
    # 方式1：从DataLoader获得Recording对象
    from core.data_loader import DataLoader
    loader = DataLoader(data_path)
    loader.load_spikeglx()
    neural_data = loader.get_spikeglx_data()
    sorter = SpikeSorter(neural_data)
    # 或者使用类方法
    sorter = SpikeSorter.from_recording(neural_data)
    
    # 方式2：直接从文件夹路径
    sorter = SpikeSorter("/path/to/spikeglx/data")
    # 或者使用类方法
    sorter = SpikeSorter.from_folder("/path/to/spikeglx/data")
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非交互式后端，适合Streamlit
from pathlib import Path
from typing import Dict, Any, Optional
import shutil
import io
import base64

try:
    import spikeinterface.full as si
    import spikeinterface.sorters as ss
    from kilosort.io import load_ops
    SPIKEINTERFACE_AVAILABLE = True
    KILOSORT_AVAILABLE = True
except ImportError:
    SPIKEINTERFACE_AVAILABLE = False
    KILOSORT_AVAILABLE = False

from utils.logger import ProcessLogger
from utils.error_handler import ProcessingError, error_boundary
from utils.config_manager import get_config_manager


class SpikeSorter:
    """
    尖峰排序器类
    
    使用Kilosort4进行神经尖峰排序，复现for_sorter.md的完整流程
    """
    
    def __init__(self, data_source, params: Optional[Dict] = None):
        """
        初始化尖峰排序器
        
        Args:
            data_source: 可以是以下两种类型之一：
                - str/Path: SpikeGLX数据文件夹路径
                - SpikeInterface Recording对象: 已加载的神经数据
            params: 排序参数
        """
        self.params = params or self.default_params()
        self.logger = ProcessLogger()
        
        # 数据源类型和路径
        self.data_source = data_source
        self.spikeglx_folder = None
        self.data_source_type = None
        
        # 处理结果存储
        self.raw_recording = None
        self.preprocessed_recording = None
        self.sorting_result = None
        self.sorting_analyzer = None  # 新增：SpikeInterface分析器
        self.output_folder = None
        self.temp_folder = None
        
        # Kilosort输出数据
        self.spike_times = None
        self.spike_clusters = None
        self.templates = None
        self.channel_map = None
        self.ops = None
        self.firing_rates = None
        self.camps = None
        self.contam_pct = None
        
        # 新增：后处理结果存储
        self.waveforms = None
        self.spike_amplitudes = None
        self.spike_locations = None
        self.unit_locations = None
        self.quality_metrics = None
        self.template_metrics = None
        self.spike_times_ms = None  # 以毫秒为单位的尖峰时间
        
        # 可视化存储
        self.visualizations = {}
        
        # 验证依赖项和数据源
        self._check_dependencies()
        self._process_data_source()
        self.save_path = self.spikeglx_folder.parent / "processed"
        self.save_path.mkdir(exist_ok=True, parents=True)
    
    def _check_dependencies(self):
        """检查必要的依赖项"""
        if not SPIKEINTERFACE_AVAILABLE:
            raise ProcessingError("SpikeInterface和Kilosort未安装，无法进行尖峰排序")
    
    def _process_data_source(self):
        """
        处理数据源，判断类型并进行相应初始化
        """
        try:
            # 检查是否为 SpikeInterface Recording 对象
            if hasattr(self.data_source, 'get_sampling_frequency') and \
               hasattr(self.data_source, 'get_num_channels') and \
               hasattr(self.data_source, 'get_traces'):
                
                # 这是一个 Recording 对象
                self.data_source_type = 'recording'
                self.raw_recording = self.data_source
                
                # 尝试从Recording对象获取原始文件夹路径信息（如果可用）
                if hasattr(self.data_source, 'folder') and self.data_source.folder:
                    self.spikeglx_folder = Path(self.data_source.folder)
                elif hasattr(self.data_source, '_kwargs') and 'folder_path' in self.data_source._kwargs:
                    self.spikeglx_folder = Path(self.data_source._kwargs['folder_path'])
                else:
                    # 使用通用名称，用于输出文件夹
                    self.spikeglx_folder = Path("./spikeglx_data")
                
                self.logger.log_info("使用预加载的Recording对象初始化SpikeSorter")
                self.logger.log_info(f"采样频率: {self.raw_recording.get_sampling_frequency()} Hz")
                self.logger.log_info(f"通道数: {self.raw_recording.get_num_channels()}")
                
            else:
                # 这应该是一个路径字符串
                self.data_source_type = 'folder'
                self.spikeglx_folder = Path(self.data_source)
                
                if not self.spikeglx_folder.exists():
                    raise ProcessingError(f"SpikeGLX数据文件夹不存在: {self.spikeglx_folder}")
                
                self.logger.log_info(f"使用数据文件夹路径初始化SpikeSorter: {self.spikeglx_folder}")
                
        except Exception as e:
            raise ProcessingError(f"处理数据源失败: {str(e)}")
    
    @classmethod
    def from_recording(cls, recording_obj, params: Optional[Dict] = None):
        """
        从预加载的Recording对象创建SpikeSorter实例
        
        Args:
            recording_obj: SpikeInterface Recording对象
            params: 排序参数
            
        Returns:
            SpikeSorter实例
        """
        return cls(recording_obj, params)
    
    @classmethod
    def from_folder(cls, folder_path: str, params: Optional[Dict] = None):
        """
        从数据文件夹路径创建SpikeSorter实例
        
        Args:
            folder_path: SpikeGLX数据文件夹路径
            params: 排序参数
            
        Returns:
            SpikeSorter实例
        """
        return cls(folder_path, params)
    
    def default_params(self) -> Dict[str, Any]:
        """
        获取默认参数 - 保持向后兼容
        
        Returns:
            默认参数字典
        """
        config_manager = get_config_manager()
        
        # 优先使用新的 spike_sorting_pipeline 配置
        pipeline_config = config_manager.get_spike_sorting_pipeline_config()
        if pipeline_config:
            return {
                'use_protocol_pipeline': True,
                'preprocessing': config_manager.get_preprocessing_protocol(),
                'sorting': config_manager.get_sorting_protocol(),
                'postprocessing': config_manager.get_postprocessing_protocol(),
                'job_kwargs': config_manager.get_job_kwargs()
            }
        else:
            # 向后兼容旧配置
            kilosort_config = config_manager.get_kilosort_config()
            return {
                'use_protocol_pipeline': False,
                'n_jobs': kilosort_config.get('n_jobs', 12),
                'chunk_duration': kilosort_config.get('chunk_duration', '4s'),
                'nblocks': kilosort_config.get('nblocks', 15),
                'Th_learned': kilosort_config.get('Th_learned', 7.0),
                'freq_min': kilosort_config.get('preprocessing', {}).get('freq_min', 300.0),
            }
    
    @error_boundary("加载SpikeGLX数据")
    def load_recording(self) -> bool:
        """
        加载SpikeGLX数据，复现for_sorter.md的加载逻辑
        支持两种情况：1）从文件夹加载 2）使用已加载的Recording对象
        
        Returns:
            是否成功加载
        """
        step_idx = self.logger.start_step("load_recording", "加载SpikeGLX数据")
        
        try:
            if not SPIKEINTERFACE_AVAILABLE:
                raise ProcessingError("SpikeInterface不可用")
            
            if self.data_source_type == 'recording':
                # 如果已经有Recording对象，直接使用
                if self.raw_recording is None:
                    raise ProcessingError("Recording对象为空")
                
                self.logger.log_info("使用预加载的Recording对象")
                
                # 记录probe信息
                try:
                    probe_df = self.raw_recording.get_probe().to_dataframe()
                    self.logger.log_info(f"Probe信息: {len(probe_df)}个通道")
                except Exception as e:
                    self.logger.log_warning(f"无法获取probe信息: {str(e)}")
                
            elif self.data_source_type == 'folder':
                # 从文件夹加载数据
                
                # 获取stream信息
                stream_names, __ = si.get_neo_streams('spikeglx', str(self.spikeglx_folder))
                self.logger.log_info(f"发现数据流: {stream_names}")
                
                # 加载AP数据
                self.raw_recording = si.read_spikeglx(
                    str(self.spikeglx_folder), 
                    stream_name='imec0.ap', 
                    load_sync_channel=False
                )
                
                # 记录probe信息
                probe_df = self.raw_recording.get_probe().to_dataframe()
                self.logger.log_info(f"Probe信息: {len(probe_df)}个通道")
                
            else:
                raise ProcessingError(f"未知的数据源类型: {self.data_source_type}")
            
            self.logger.complete_step(step_idx, True, "数据加载完成")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"数据加载失败: {str(e)}")
    
    @error_boundary("数据预处理")
    def preprocess(self) -> bool:
        """
        数据预处理 - 支持新的protocol pipeline和向后兼容
        
        Returns:
            是否成功预处理
        """
        step_idx = self.logger.start_step("preprocessing", "神经数据预处理")
        
        try:
            if self.raw_recording is None:
                raise ProcessingError("请先加载数据")
            
            recording = self.raw_recording
            
            # 检查是否使用新的protocol pipeline
            if self.params.get('use_protocol_pipeline', False):
                self.logger.log_info("使用SpikeInterface Protocol Pipeline进行预处理")
                raw_channel_ids = recording.channel_ids
                # 获取预处理协议
                preprocessing_protocol = self.params.get('preprocessing', {})
                self.logger.log_parameters(preprocessing_protocol, "预处理协议")
                
                # 应用预处理pipeline
                self.logger.log_info("应用预处理pipeline...")
                recording = si.apply_preprocessing_pipeline(recording, preprocessing_protocol)
                new_channel_ids = recording.channel_ids
                removed_channel_ids = np.setdiff1d(raw_channel_ids, new_channel_ids)
                self.logger.log_info(f"移除了{len(removed_channel_ids)}个坏道: {removed_channel_ids}")
            
            else:
                # 向后兼容：使用旧的手动步骤
                self.logger.log_info("使用传统手动预处理步骤")
                
                # 1. 高通滤波
                freq_min = self.params.get('freq_min', 300.0)
                self.logger.log_info(f"应用高通滤波 (freq_min={freq_min}Hz)...")
                recording = si.highpass_filter(recording=recording, freq_min=freq_min)
                
                # 2. 检测坏道
                self.logger.log_info("检测坏道...")
                bad_channel_ids, _ = si.detect_bad_channels(recording)
                self.logger.log_info(f"发现坏道: {bad_channel_ids}")
                
                # 3. 移除坏道
                if len(bad_channel_ids) > 0:
                    recording = recording.remove_channels(bad_channel_ids)
                    self.logger.log_info(f"移除了{len(bad_channel_ids)}个坏道")
                
                # 4. 相位偏移校正 
                self.logger.log_info("应用相位偏移校正...")
                recording = si.phase_shift(recording)
                
                # 5. 共同参考 
                self.logger.log_info("应用共同参考...")
                recording = si.common_reference(recording, operator="median", reference="global")
            
            # 获取作业参数
            if self.params.get('use_protocol_pipeline', False):
                sorting_params = self.params.get('sorting', {})
                remove_existing_folder = sorting_params.get('remove_existing_folder', True)
                job_kwargs = {
                    'n_jobs': sorting_params.get('n_jobs', 12),
                    'chunk_duration': sorting_params.get('chunk_duration', '4s'),
                    'progress_bar': sorting_params.get('progress_bar', True)
                }
            else:
                remove_existing_folder = sorting_params.get('remove_existing_folder', True)
                job_kwargs = {
                    'n_jobs': self.params.get('n_jobs', 12),
                    'chunk_duration': self.params.get('chunk_duration', '4s'),
                    'progress_bar': True
                }
            
            # 保存预处理后的数据到临时文件夹
            self.temp_folder = self.save_path / 'KS_TEMP'
            if self.temp_folder.exists():
                if remove_existing_folder:
                    shutil.rmtree(self.temp_folder)
                else:
                    self.logger.log_warning(f"临时文件夹已存在, 尝试读取{self.temp_folder}")
                    try:
                        self.preprocessed_recording = si.load(self.temp_folder, format='zarr')
                    except Exception as e:
                        raise ProcessingError(f"加载预处理数据失败: {e}")
            
            self.logger.log_info("保存预处理数据...")
            self.preprocessed_recording = recording.save(
                folder=str(self.temp_folder), 
                format='zarr', 
                **job_kwargs
            )

            self.logger.complete_step(step_idx, True, "预处理完成")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"数据预处理失败: {str(e)}")
    
    @error_boundary("Kilosort排序")
    def run_kilosort(self, output_folder: Optional[str] = None) -> bool:
        """
        运行Kilosort进行尖峰排序 - 支持新的protocol pipeline和向后兼容
        
        Args:
            output_folder: 输出文件夹路径
            
        Returns:
            是否成功完成排序
        """
        step_idx = self.logger.start_step("kilosort", "运行Kilosort进行尖峰排序")
        
        try:
            if self.preprocessed_recording is None:
                self.temp_folder = self.save_path / 'KS_TEMP'
                if not os.path.exists(self.temp_folder):    
                    raise ProcessingError("请先进行数据预处理")
                else:
                    try:
                        self.logger.log_info(f"加载预处理数据: {self.temp_folder}")
                        self.preprocessed_recording = si.load(self.temp_folder)
                    except Exception as e:
                        raise ProcessingError(f"加载预处理数据失败: {e}")
            
            # 设置输出文件夹
            if output_folder is None:
                output_folder = self.save_path / "kilosort_output"
            
            self.output_folder = Path(output_folder)
            self.logger.log_info(f"输出目录: {self.output_folder}")
            
            # 检查是否使用新的protocol pipeline
            if self.params.get('use_protocol_pipeline', False):
                self.logger.log_info("使用SpikeInterface Protocol Pipeline进行排序")
                
                # 获取排序协议
                sorting_protocol = self.params.get('sorting', {})
                self.logger.log_parameters(sorting_protocol, "排序协议")
                
                # 运行排序
                self.logger.log_info("开始运行排序...")
                self.sorting_result = si.run_sorter(
                    recording=self.preprocessed_recording,
                    folder=str(self.output_folder),
                    **sorting_protocol
                )
                
                
                # 创建SortingAnalyzer
                self.logger.log_info("创建SortingAnalyzer...")
                self.sorting_analyzer = si.create_sorting_analyzer(
                    recording=self.preprocessed_recording,
                    sorting=self.sorting_result,
                    format="binary_folder",
                    folder=self.save_path / "sorting_analyzer"
                )
                
                # 运行后处理
                postprocessing_protocol = self.params.get('postprocessing', {})
                job_kwargs = self.params.get('job_kwargs', {})
                if postprocessing_protocol:
                    self.logger.log_info("运行后处理扩展...")
                    self.logger.log_parameters(postprocessing_protocol, "后处理协议")
                    self.sorting_analyzer.compute(postprocessing_protocol, **job_kwargs)
                    
                    # 提取后处理结果
                    self._extract_postprocessing_results()
                
            else:
                # 向后兼容：使用旧的方法
                self.logger.log_info("使用传统排序方法")
                self.logger.log_parameters(self.params, "Kilosort参数")
                
                # 准备 sorter 参数
                kilosort_params = self._prepare_kilosort_params()
                
                self.logger.log_info("开始运行Kilosort4...")
                
                # 使用SpikeInterface运行Kilosort4
                self.sorting_result = ss.run_sorter(
                    sorter_name="kilosort4",
                    recording=self.preprocessed_recording,
                    folder=str(self.output_folder),
                    **kilosort_params
                )
            
            # 加载Kilosort输出结果
            self._load_kilosort_outputs()
            
            # 生成排序摘要和可视化
            summary = self._generate_sorting_summary()
            self.logger.log_results(summary, "Kilosort结果")
            
            # 生成可视化图表
            self._generate_visualizations()

            # 清理临时文件夹
            del self.preprocessed_recording
            import gc
            gc.collect()
            self._cleanup_temp_folder()
            
            self.logger.complete_step(step_idx, True, "Kilosort完成")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"Kilosort失败: {str(e)}")
    
    def _extract_postprocessing_results(self):
        """提取后处理结果到实例变量中"""
        try:
            if self.sorting_analyzer is None:
                return
            
            sampling_frequency = self.preprocessed_recording.get_sampling_frequency()
            
            # 提取波形数据
            if self.sorting_analyzer.has_extension('waveforms'):
                self.waveforms = self.sorting_analyzer.get_extension('waveforms').get_data()
                self.logger.log_info("提取波形数据完成")
            
            # 提取尖峰振幅
            if self.sorting_analyzer.has_extension('spike_amplitudes'):
                self.spike_amplitudes = self.sorting_analyzer.get_extension('spike_amplitudes').get_data()
                self.logger.log_info("提取尖峰振幅完成")
            
            # 提取尖峰位置
            if self.sorting_analyzer.has_extension('spike_locations'):
                self.spike_locations = self.sorting_analyzer.get_extension('spike_locations').get_data()
                self.logger.log_info("提取尖峰位置完成")
            
            # 提取单元位置
            if self.sorting_analyzer.has_extension('unit_locations'):
                self.unit_locations = self.sorting_analyzer.get_extension('unit_locations').get_data()
                self.logger.log_info("提取单元位置完成")
            
            # 提取模板
            if self.sorting_analyzer.has_extension('templates'):
                self.templates = self.sorting_analyzer.get_extension('templates').get_data()
                self.logger.log_info("提取模板数据完成")
            
            # 提取质量指标
            if self.sorting_analyzer.has_extension('quality_metrics'):
                self.quality_metrics = self.sorting_analyzer.get_extension('quality_metrics').get_data()
                self.logger.log_info("提取质量指标完成")
            
            # 提取模板指标
            if self.sorting_analyzer.has_extension('template_metrics'):
                self.template_metrics = self.sorting_analyzer.get_extension('template_metrics').get_data()
                self.logger.log_info("提取模板指标完成")
            
            # 计算以毫秒为单位的尖峰时间
            if self.sorting_result is not None:
                spike_times_samples = self.sorting_result.get_all_spike_trains()[0] if len(self.sorting_result.get_all_spike_trains()) > 0 else None
                if spike_times_samples is not None:
                    self.spike_times_ms = spike_times_samples / sampling_frequency * 1000
                    self.logger.log_info("计算尖峰时间(ms)完成")
            
            self.logger.log_info("后处理结果提取完成")
            
        except Exception as e:
            self.logger.log_warning(f"提取后处理结果时出错: {e}")
    
    def _cleanup_temp_folder(self):
        """清理临时文件夹"""
        if self.temp_folder and self.temp_folder.exists():
            try:
                shutil.rmtree(self.temp_folder)
                self.logger.log_info(f"临时文件夹 '{self.temp_folder}' 已被删除")
            except Exception as e:
                self.logger.log_warning(f"清理临时文件夹失败: {e}")
    
    def _load_kilosort_outputs(self):
        """加载Kilosort输出结果，复现for_sorter.md的结果加载"""
        try:
            results_dir = self.output_folder / 'sorter_output'
            
            if not results_dir.exists():
                raise ProcessingError(f"Kilosort输出目录不存在: {results_dir}")
            
            # 加载ops (复现: ops = load_ops(results_dir / 'ops.npy'))
            if KILOSORT_AVAILABLE:
                self.ops = load_ops(results_dir / 'ops.npy')
            
            # 加载聚类振幅 (复现: camps = pd.read_csv(...))
            camps_file = results_dir / 'cluster_Amplitude.tsv'
            if camps_file.exists():
                self.camps = pd.read_csv(camps_file, sep='\t')['Amplitude'].values
            
            # 加载污染百分比 (复现: contam_pct = pd.read_csv(...))
            contam_file = results_dir / 'cluster_ContamPct.tsv'
            if contam_file.exists():
                self.contam_pct = pd.read_csv(contam_file, sep='\t')['ContamPct'].values
            
            # 加载通道映射 (复现: chan_map = np.load(...))
            chan_map_file = results_dir / 'channel_map.npy'
            if chan_map_file.exists():
                self.channel_map = np.load(chan_map_file)
            
            # 加载模板 (复现: templates = np.load(...))
            templates_file = results_dir / 'templates.npy'
            if templates_file.exists():
                self.templates = np.load(templates_file)
            
            # 加载振幅 (复现: amplitudes = np.load(...))
            amplitudes_file = results_dir / 'amplitudes.npy'
            if amplitudes_file.exists():
                self.amplitudes = np.load(amplitudes_file)
            
            # 加载尖峰时间 (复现: st = np.load(...))
            spike_times_file = results_dir / 'spike_times.npy'
            if spike_times_file.exists():
                self.spike_times = np.load(spike_times_file)
            
            # 加载聚类 (复现: clu = np.load(...))
            spike_clusters_file = results_dir / 'spike_clusters.npy'
            if spike_clusters_file.exists():
                self.spike_clusters = np.load(spike_clusters_file)
            
            # 计算发放率 (复现: firing_rates = np.unique(clu, return_counts=True)[1] * 30000 / st.max())
            if self.spike_clusters is not None and self.spike_times is not None:
                unique_clusters, counts = np.unique(self.spike_clusters, return_counts=True)
                self.firing_rates = counts * 30000 / self.spike_times.max()
            
            self.logger.log_info("Kilosort输出结果加载完成")
            
        except Exception as e:
            self.logger.log_error(f"加载Kilosort输出失败: {e}")
            raise
    
    def _prepare_kilosort_params(self) -> Dict[str, Any]:
        """准备Kilosort参数"""
        return {
            'nblocks': self.params.get('nblocks', 15),
            'Th_learned': self.params.get('Th_learned', 7.0)
        }
    
    def _generate_visualizations(self):
        """生成可视化图表，复现for_sorter.md的可视化代码"""
        try:
            pass
            
        except Exception as e:
            self.logger.log_error(f"可视化生成失败: {str(e)}")
            # 继续处理，不中断流程
    
    def _generate_sorting_summary(self) -> Dict[str, Any]:
        """生成排序摘要"""
        summary = {}
        
        try:
            if self.spike_clusters is not None:
                unique_units = np.unique(self.spike_clusters)
                num_units = len(unique_units)
                total_spikes = len(self.spike_times) if self.spike_times is not None else 0
                
                summary.update({
                    'num_units': int(num_units),
                    'total_spikes': int(total_spikes),
                    'output_folder': str(self.output_folder)
                })
                
                if self.firing_rates is not None:
                    summary['average_firing_rate'] = float(np.mean(self.firing_rates))
                    summary['max_firing_rate'] = float(np.max(self.firing_rates))
                    summary['min_firing_rate'] = float(np.min(self.firing_rates))
                
                if self.camps is not None:
                    summary['average_amplitude'] = float(np.mean(self.camps))
                
                if self.contam_pct is not None:
                    good_units = np.sum(self.contam_pct < 10.0)
                    summary['good_units'] = int(good_units)
                    summary['good_unit_percentage'] = float(good_units / num_units * 100)
                    
        except Exception as e:
            self.logger.log_warning(f"生成排序摘要时出错: {e}")
        
        return summary
    
    # 新增的完整处理流程方法
    @error_boundary("完整尖峰排序流程")
    def run_full_pipeline(self, output_folder: Optional[str] = None) -> bool:
        """
        运行完整的尖峰排序流程
        
        Args:
            output_folder: 输出文件夹路径
            
        Returns:
            是否成功完成
        """
        step_idx = self.logger.start_step("full_pipeline", "运行完整尖峰排序流程")
        
        try:
            # 1. 加载数据（如果需要）
            if self.data_source_type == 'folder':
                self.logger.log_info("步骤1: 加载SpikeGLX数据")
                if not self.load_recording():
                    raise ProcessingError("数据加载失败")
            else:
                # 使用预加载的Recording对象，验证数据有效性
                self.logger.log_info("步骤1: 验证预加载的Recording对象")
                if not self.load_recording():  # 这会验证并设置probe信息
                    raise ProcessingError("预加载数据验证失败")
            
            # 2. 预处理
            self.logger.log_info("步骤2: 数据预处理")
            if not self.preprocess():
                raise ProcessingError("数据预处理失败")
            
            # 3. 运行Kilosort
            self.logger.log_info("步骤3: 运行Kilosort排序")
            if not self.run_kilosort(output_folder):
                raise ProcessingError("Kilosort排序失败")
            
            self.logger.complete_step(step_idx, True, "完整尖峰排序流程完成")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"完整排序流程失败: {str(e)}")
    
    # 获取结果的方法
    def get_visualizations(self) -> Dict[str, str]:
        """获取可视化图表的base64编码"""
        return self.visualizations.copy()
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """获取排序摘要统计"""
        return self._generate_sorting_summary()
    
    def get_quality_metrics(self) -> Dict[str, Any]:
        """获取质量评估指标"""
        if self.contam_pct is None or self.firing_rates is None:
            return {}
        
        return {
            'good_units': int(np.sum(self.contam_pct < 10.0)),
            'total_units': len(self.contam_pct),
            'contamination_stats': {
                'mean': float(np.mean(self.contam_pct)),
                'median': float(np.median(self.contam_pct)),
                'std': float(np.std(self.contam_pct))
            },
            'firing_rate_stats': {
                'mean': float(np.mean(self.firing_rates)),
                'median': float(np.median(self.firing_rates)),
                'std': float(np.std(self.firing_rates))
            }
        }
    
    def get_sorting_result(self):
        """获取排序结果"""
        return self.sorting_result
    
    def get_sorting_analyzer(self):
        """获取SortingAnalyzer对象"""
        return self.sorting_analyzer
    
    def get_output_folder(self) -> Optional[Path]:
        """获取输出文件夹路径"""
        return self.output_folder
    
    def cleanup_temp_files(self):
        """清理临时文件"""
        self._cleanup_temp_folder()
    
    # 新增：获取后处理结果的方法
    def get_waveforms(self):
        """获取波形数据"""
        return self.waveforms
    
    def get_spike_amplitudes(self):
        """获取尖峰振幅"""
        return self.spike_amplitudes
    
    def get_spike_locations(self):
        """获取尖峰位置"""
        return self.spike_locations
    
    def get_unit_locations(self):
        """获取单元位置"""
        return self.unit_locations
    
    def get_spike_times_ms(self):
        """获取以毫秒为单位的尖峰时间"""
        return self.spike_times_ms
    
    def get_template_metrics(self):
        """获取模板指标"""
        return self.template_metrics
    
    def get_postprocessing_summary(self) -> Dict[str, Any]:
        """获取后处理数据摘要"""
        summary = {}
        
        if self.waveforms is not None:
            summary['waveforms_shape'] = str(self.waveforms.shape)
            summary['waveforms_available'] = True
        else:
            summary['waveforms_available'] = False
            
        if self.spike_amplitudes is not None:
            summary['spike_amplitudes_count'] = len(self.spike_amplitudes)
            summary['spike_amplitudes_available'] = True
        else:
            summary['spike_amplitudes_available'] = False
            
        if self.spike_locations is not None:
            summary['spike_locations_count'] = len(self.spike_locations)
            summary['spike_locations_available'] = True
        else:
            summary['spike_locations_available'] = False
            
        if self.unit_locations is not None:
            summary['unit_locations_count'] = len(self.unit_locations)
            summary['unit_locations_available'] = True
        else:
            summary['unit_locations_available'] = False
            
        if self.spike_times_ms is not None:
            summary['spike_times_ms_count'] = len(self.spike_times_ms)
            summary['spike_times_ms_available'] = True
        else:
            summary['spike_times_ms_available'] = False
            
        if self.quality_metrics is not None:
            summary['quality_metrics_available'] = True
            summary['quality_metrics_columns'] = list(self.quality_metrics.columns) if hasattr(self.quality_metrics, 'columns') else "N/A"
        else:
            summary['quality_metrics_available'] = False
            
        return summary
    
    def load_existing_results(self, results_folder: str) -> bool:
        """
        加载已有的排序结果
        
        Args:
            results_folder: 结果文件夹路径
            
        Returns:
            是否成功加载
        """
        try:
            self.output_folder = Path(results_folder)
            self._load_kilosort_outputs()
            self.logger.log_info(f"成功加载排序结果: {results_folder}")
            return True
            
        except Exception as e:
            self.logger.log_error(f"加载排序结果失败: {e}")
            return False
