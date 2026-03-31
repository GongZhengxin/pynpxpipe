"""
数据整合模块

负责整合排序结果、质量控制和行为数据，进行神经元响应分析
输出为 nwbfile (主要功能)
或者为 mat 文件 (次要功能,暂不实现)
"""

import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime

import h5py
import numpy as np
import pandas as pd
from tqdm import tqdm
from dateutil import tz
from scipy.stats import mannwhitneyu

# NWB 相关导入
from pynwb import NWBHDF5IO
from pynwb.behavior import SpatialSeries, EyeTracking

# NeuroConv 相关导入
from neuroconv.converters import SpikeGLXConverterPipe
from neuroconv.datainterfaces import KiloSortSortingInterface
from neuroconv.tools.nwb_helpers import get_default_backend_configuration
from neuroconv.utils.dict import load_dict_from_file, dict_deep_update

# 导入辅助函数
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from utils.nwb_stim_helper import StimulusImageManager
from utils.nwb_bombcell_helper import (
    add_bombcell_columns_to_nwb,
    get_bombcell_metrics_for_unit
)
from utils.config_manager import get_config_manager
from utils.logger import setup_logger


class DataIntegrator:
    """
    数据整合类
    
    负责将电生理数据、排序结果、质量控制和行为数据整合到 NWB 文件中
    """
    
    def __init__(self, 
                 data_path: Union[str, Path],
                 info_yaml: Optional[Union[str, Path]] = None,
                 output_folder: Optional[Union[str, Path]] = None,
                 target_area: Optional[str] = None,
                 logger=None):
        """
        初始化数据整合器
        
        Args:
            data_path: 项目根目录路径
            info_yaml: session info 文件路径（例如 MaoDan.yaml）
            output_folder: 输出文件夹路径
            target_area: 电极位置（可选，例如 "MLO"）
            logger: 日志记录器（可选）
        """
        self.data_path = Path(data_path)
        
        # 加载配置
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_data_integrator_config()
        
        # 设置日志
        self.logger = logger or setup_logger(
            "DataIntegrator",
            log_level=self.config.get("logging", {}).get("level", "INFO")
        )
        
        # 设置路径
        self._setup_paths(info_yaml, output_folder, target_area)
        
        # 初始化变量
        self.nwbfile_path = None
        self.converter = None
        self.metadata = None

        with h5py.File(self.meta_file_path, 'r') as f:
            exp_day = f['session_info'].attrs['exp_day']
            exp_monkey = f['session_info'].attrs['exp_subject']
            exp_dataset = f['session_info'].attrs['dataset_name']
            self.session_id = f"{exp_day}_{exp_monkey}_{exp_dataset}_{target_area}"
        
    def _setup_paths(self, info_yaml, output_folder, target_area):
        """设置所有必要的路径"""
        # 查找 SpikeGLX 文件夹
        pattern = self.config['folder_structure']['spikeglx_folder_pattern']
        spikeglx_folders = list(self.data_path.glob(pattern))
        if not spikeglx_folders:
            raise FileNotFoundError(f"找不到匹配 {pattern} 的 SpikeGLX 文件夹")
        self.spikeglx_path = spikeglx_folders[0]
        self.logger.info(f"找到 SpikeGLX 数据: {self.spikeglx_path}")
        
        # 设置处理后的数据路径
        processed_folder = self.config['folder_structure']['processed_folder']
        self.processed_path = self.data_path / processed_folder
        
        # Kilosort 路径
        ks_folder = self.config['folder_structure']['kilosort_folder']
        self.ks_path = self.processed_path / ks_folder
        if not self.ks_path.exists():
            raise FileNotFoundError(f"找不到 Kilosort 输出文件夹: {self.ks_path}")
        
        # Bombcell 路径
        bc_folder = self.config['folder_structure']['bombcell_folder']
        self.bc_path = self.processed_path / bc_folder
        if not self.bc_path.exists():
            raise FileNotFoundError(f"找不到 Bombcell 输出文件夹: {self.bc_path}")
        
        # META 文件路径
        meta_pattern = self.config['folder_structure']['meta_file_pattern']
        meta_files = list(self.processed_path.glob(meta_pattern))
        if not meta_files:
            raise FileNotFoundError(f"找不到匹配 {meta_pattern} 的 META 文件")
        self.meta_file_path = meta_files[0]
        self.logger.info(f"找到 META 文件: {self.meta_file_path}")
        
        # 输出文件夹
        if output_folder:
            self.output_folder = Path(output_folder)
        else:
            self.output_folder = self.data_path.parent / "nwbfiles"
        self.output_folder.mkdir(parents=True, exist_ok=True)
        
        # 受试者配置
        self.info_yaml = info_yaml
        if info_yaml and not Path(info_yaml).is_absolute():
            self.info_yaml = Path(__file__).parent.parent / "config" / info_yaml
        
        # 电极位置
        self.electrode_location = target_area
        
    def _create_converter(self):
        """创建 SpikeGLX 转换器"""
        self.logger.info("创建 SpikeGLX 转换器...")
        verbose = self.config.get("logging", {}).get("verbose", True)
        self.converter = SpikeGLXConverterPipe(
            folder_path=self.spikeglx_path,
            verbose=verbose
        )
        
    def _prepare_metadata(self):
        """准备元数据"""
        self.logger.info("准备元数据...")
        
        # 从源文件提取元数据
        self.metadata = self.converter.get_metadata()
        
        # 添加时区信息
        session_start_time = self.metadata["NWBFile"]["session_start_time"].replace(
            tzinfo=tz.tzlocal()
        )
        self.metadata["NWBFile"].update(session_start_time=session_start_time)
        
        # 加载 session 模板
        config_dir = Path(__file__).parent.parent / "config"
        session_template_path = config_dir / self.config['metadata']['session_template']
        if session_template_path.exists():
            session_metadata = load_dict_from_file(file_path=str(session_template_path))
            self.metadata = dict_deep_update(session_metadata, self.metadata)
        
        # 加载 subject 模板
        if self.info_yaml and Path(self.info_yaml).exists():
            subject_metadata = load_dict_from_file(file_path=str(self.info_yaml))
            self.metadata = dict_deep_update(subject_metadata, self.metadata)
        
        # 设置电极位置
        if self.electrode_location:
            self.metadata["Ecephys"]["ElectrodeGroup"][0]["location"] = self.electrode_location
        
        # 初始化 TimeSeries 字典（如果不存在）
        # SpikeGLX NIDQ 接口需要这个键来添加模拟通道数据
        if "TimeSeries" not in self.metadata:
            self.metadata["TimeSeries"] = {}
        
    def _get_backend_configuration(self):
        """获取后端配置"""
        self.logger.info("配置后端参数...")
        
        # 创建 NWB 文件对象
        nwbfile = self.converter.create_nwbfile(metadata=self.metadata)
        backend_configurations = get_default_backend_configuration(
            nwbfile=nwbfile,
            backend="hdf5",
        )
        
        # 应用压缩配置
        dataset_configurations = backend_configurations.dataset_configurations
        
        # AP 配置
        ap_config = dataset_configurations["acquisition/ElectricalSeriesAP/data"]
        ap_settings = self.config['nwb']['compression']['ap']
        ap_config.chunk_shape = (1, 64)
        ap_config.buffer_shape = tuple(ap_settings.get('buffer_shape', ap_settings['chunk_shape']))
        ap_config.chunk_shape = tuple(ap_settings['chunk_shape'])
        ap_config.compression_method = ap_settings['compression_method']
        ap_config.compression_options = ap_settings['compression_options']
        
        # LF 配置
        lf_config = dataset_configurations["acquisition/ElectricalSeriesLF/data"]
        lf_settings = self.config['nwb']['compression']['lf']
        lf_config.chunk_shape = (1, 64)
        lf_config.buffer_shape = tuple(lf_settings['buffer_shape'])
        lf_config.chunk_shape = tuple(lf_settings['chunk_shape'])
        lf_config.compression_method = lf_settings['compression_method']
        lf_config.compression_options = lf_settings['compression_options']
        
        return backend_configurations
    
    def _get_conversion_options(self):
        """获取转换选项"""
        conv_config = self.config['nwb']['conversion_options']
        
        conversion_options = {
            "imec0.ap": {
                "stub_test": conv_config['ap']['stub_test'],
                "iterator_opts": dict(
                    display_progress=conv_config['ap']['display_progress']
                ),
            },
            "imec0.lf": {
                "stub_test": conv_config['lf']['stub_test'],
                "iterator_opts": dict(
                    display_progress=conv_config['lf']['display_progress']
                ),
            },
        }
        
        return conversion_options
    
    def step1_convert_raw_data(self, output_filename: Optional[str] = None):
        """
        Step 1: 转换原始数据到 NWB 文件
        
        Args:
            output_filename: 输出文件名（可选）
        """
        self.logger.info("=" * 60)
        self.logger.info("Step 1: 转换原始数据到 NWB 文件")
        self.logger.info("=" * 60)
        
        # 创建转换器
        self._create_converter()
        
        # 准备元数据
        self._prepare_metadata()
        
        # 生成输出文件路径
        if output_filename is None: 
            session_id = self.session_id
            pattern = self.config['output']['output_filename_pattern']
            output_filename = pattern.format(session_id=session_id)
        
        self.nwbfile_path = self.output_folder / output_filename
        
        # 检查文件是否存在
        if self.nwbfile_path.exists():
            if self.config['output']['overwrite']:
                self.logger.warning(f"覆盖已存在的文件: {self.nwbfile_path}")
                self.nwbfile_path.unlink()
            else:
                self.logger.info(f"NWB 文件已存在: {self.nwbfile_path}")
                return
        
        # 获取配置
        backend_configurations = self._get_backend_configuration()
        conversion_options = self._get_conversion_options()
        
        # 执行转换
        self.logger.info(f"开始转换，输出文件: {self.nwbfile_path}")
        self.converter.run_conversion(
            nwbfile_path=self.nwbfile_path,
            metadata=self.metadata,
            conversion_options=conversion_options,
            backend_configuration=backend_configurations
        )
        
        self.logger.info("✓ Step 1 完成: 原始数据已转换")
        
    def step2_add_kilosort_results(self):
        """
        Step 2: 添加 Kilosort 排序结果
        """
        self.logger.info("=" * 60)
        self.logger.info("Step 2: 添加 Kilosort 排序结果")
        self.logger.info("=" * 60)
        
        if not self.nwbfile_path or not self.nwbfile_path.exists():
            raise FileNotFoundError(f"NWB 文件不存在: {self.nwbfile_path}")
        
        # 检查是否已添加
        ks_config = self.config['kilosort']
        units_name = ks_config['units_name']
        
        try:
            with NWBHDF5IO(self.nwbfile_path, 'r') as io:
                nwbfile_temp = io.read()
                has_kilosort = (
                    nwbfile_temp.processing and
                    'ecephys' in nwbfile_temp.processing and
                    units_name in nwbfile_temp.processing['ecephys'].data_interfaces
                )
        except ValueError as e:
            # 文件损坏，需要重建
            if self.config['output']['auto_rebuild_on_error']:
                self.logger.error(f"检测到 NWB 文件损坏: {e}")
                self.logger.info("删除损坏的文件并重新生成...")
                self.nwbfile_path.unlink()
                self.step1_convert_raw_data()
                has_kilosort = False
            else:
                raise
        
        if has_kilosort:
            self.logger.info(f"Kilosort 结果已存在于 NWB 文件中")
            return
        
        # 添加 Kilosort 结果
        self.logger.info(f"从 {self.ks_path} 添加 Kilosort 结果...")
        
        with NWBHDF5IO(self.nwbfile_path, 'r+') as io:
            nwbfile = io.read()
            
            # 创建 Kilosort 接口
            verbose = self.config.get("logging", {}).get("verbose", True)
            ks_interface = KiloSortSortingInterface(
                folder_path=self.ks_path,
                verbose=verbose
            )
            
            # 转换选项
            ks_conversion_options = {
                'write_as': ks_config['write_as'],
                'units_name': units_name,
            }
            
            # 添加到 NWB 文件
            ks_interface.add_to_nwbfile(nwbfile, **ks_conversion_options)
            io.write(nwbfile)
        
        self.logger.info("✓ Step 2 完成: Kilosort 结果已添加")
        
    def step3_add_behavioral_data(self):
        """
        Step 3: 添加行为数据（trials, eye tracking, stimulus）
        """
        self.logger.info("=" * 60)
        self.logger.info("Step 3: 添加行为数据")
        self.logger.info("=" * 60)
        
        if not self.nwbfile_path or not self.nwbfile_path.exists():
            raise FileNotFoundError(f"NWB 文件不存在: {self.nwbfile_path}")
        
        # 加载 META 文件
        self.logger.info(f"从 {self.meta_file_path} 加载行为数据...")
        
        with h5py.File(self.meta_file_path, 'r') as f:
            # 加载同步和 trial 信息
            stim_start_times = f['sync_info']['stim_start_times'][:] / 1000  # 转换为秒
            stim_end_times = f['sync_info']['stim_end_times'][:] / 1000
            trial_valid_idx = f['trial_validation']['trial_valid_idx'][:].astype(np.int64)
            dataset_valid_idx = f['trial_validation']['dataset_valid_idx'][:]
            
            # 加载眼动数据
            eye_track = f['eye_data']['eye_matrix'][:]
            
            # 加载刺激信息
            stim_path = f['session_info'].attrs['dataset_path']
            stim_dataset_name = f['session_info'].attrs['dataset_name']
        
        # 读取图片名称
        image_names = pd.read_csv(stim_path, sep='\t').FileName.values
        image_names = np.insert(image_names, 0, 'None')
        trial_stim_names = image_names[trial_valid_idx]
        
        # 写入 NWB 文件
        with NWBHDF5IO(self.nwbfile_path, "r+") as io:
            nwbfile = io.read()
            
            # 添加 trial 列
            self._add_trial_columns(nwbfile)
            
            # 添加 trial 数据
            self._add_trials(
                nwbfile, stim_start_times, stim_end_times,
                trial_valid_idx, dataset_valid_idx, trial_stim_names
            )
            
            # 添加眼动数据
            self._add_eye_tracking(nwbfile, eye_track, stim_start_times)
            
            # 添加刺激数据
            if self.config['stimulus']['add_to_nwb']:
                self._add_stimulus(
                    nwbfile, stim_path, trial_valid_idx,
                    stim_start_times, stim_dataset_name
                )
            
            io.write(nwbfile)
        
        self.logger.info("✓ Step 3 完成: 行为数据已添加")
        
    def _add_trial_columns(self, nwbfile):
        """添加 trial 列"""
        trial_cols = self.config['behavioral']['trial_columns']
        for col_name, col_info in trial_cols.items():
            nwbfile.add_trial_column(
                name=col_name,
                description=col_info['description']
            )
        self.logger.info(f"添加了 {len(trial_cols)} 个 trial 列")
        
    def _add_trials(self, nwbfile, stim_start_times, stim_end_times,
                   trial_valid_idx, dataset_valid_idx, trial_stim_names):
        """添加 trial 数据"""
        n_trials = len(stim_start_times)
        
        all_trial_data = [
            {
                'start_time': stim_start_times[i],
                'stop_time': stim_end_times[i],
                'stim_index': int(trial_valid_idx[i]),
                'stim_name': trial_stim_names[i],
                'fix_success': int(dataset_valid_idx[i] != 0),
            }
            for i in range(n_trials)
        ]
        
        show_progress = self.config.get("logging", {}).get("show_progress", True)
        iterator = tqdm(enumerate(all_trial_data), total=n_trials, 
                       desc="添加 trial 数据") if show_progress else enumerate(all_trial_data)
        
        for i, trial_data in iterator:
            nwbfile.add_trial(**trial_data)
        
        self.logger.info(f"添加了 {n_trials} 个 trials")
        
    def _add_eye_tracking(self, nwbfile, eye_track, stim_start_times):
        """添加眼动追踪数据"""
        eye_config = self.config['behavioral']['eye_tracking']
        
        n_timepoint = eye_track.shape[1]
        interval = eye_config['sampling_interval']
        
        # 生成时间戳
        eyetrack_start_times = np.asarray(stim_start_times).reshape(-1, 1)
        eyetrack_timestamp = eyetrack_start_times + np.arange(n_timepoint) * interval
        eyetrack_timestamp = eyetrack_timestamp.reshape(-1)
        eye_track = eye_track.reshape((-1, 2))
        
        # 创建 behavior 模块
        behavior_module = nwbfile.create_processing_module(
            name="behavior",
            description="Processed behavioral data"
        )
        
        # 创建眼动数据
        eye_name = f"{eye_config['eye_used']}_eye_position"
        eye_positions = SpatialSeries(
            name=eye_name,
            description=f"The position of the {eye_config['eye_used']} eye measured in {eye_config['unit']}.",
            data=eye_track,
            timestamps=eyetrack_timestamp,
            reference_frame=eye_config['reference_frame'],
            unit=eye_config['unit'],
        )
        
        eye_tracking = EyeTracking(name="EyeTracking", spatial_series=eye_positions)
        behavior_module.add(eye_tracking)
        
        self.logger.info(f"添加了眼动追踪数据 ({len(eyetrack_timestamp)} 个时间点)")
        
    def _add_stimulus(self, nwbfile, stim_path, trial_valid_idx,
                     stim_start_times, stim_dataset_name):
        """添加刺激数据"""
        self.logger.info(f"添加刺激数据: {stim_dataset_name}")
        
        stim_manager = StimulusImageManager(stim_path)
        images_series, index_series = stim_manager.add_to_nwb(
            nwbfile, trial_valid_idx, stim_start_times,
            stimulus_name=stim_dataset_name
        )
        
        self.logger.info("刺激数据已添加")
        
    def step4_add_custom_units(self):
        """
        Step 4: 添加自定义 units（包含 Bombcell 质量指标和响应分析）
        """
        self.logger.info("=" * 60)
        self.logger.info("Step 4: 添加自定义 units")
        self.logger.info("=" * 60)
        
        if not self.nwbfile_path or not self.nwbfile_path.exists():
            raise FileNotFoundError(f"NWB 文件不存在: {self.nwbfile_path}")
        
        # 读取现有数据
        self.logger.info("读取现有的 units 和 trials...")
        with NWBHDF5IO(self.nwbfile_path, 'r') as io:
            nwbfile = io.read()
            units_name = self.config['kilosort']['units_name']
            unit_df = nwbfile.processing['ecephys'][units_name].to_dataframe()
            trial_df = nwbfile.trials.to_dataframe()
        
        spike_times_list = unit_df['spike_times'].values
        bc_unittype_string = unit_df['bc_unitType'].values
        n_units = len(spike_times_list)
        self.logger.info(f"找到 {n_units} 个 units")
        
        # 加载 Kilosort 数据
        spike_pos = np.load(self.ks_path / 'spike_positions.npy', mmap_mode='r')
        spike_template = np.load(self.ks_path / 'spike_templates.npy', mmap_mode='r')
        
        # 加载 Bombcell 数据
        self.logger.info(f"加载 Bombcell 数据: {self.bc_path}")
        bc_qm_df = pd.read_csv(self.bc_path / 'templates._bc_qMetrics.csv', index_col=0)
        
        # 删除全为 NaN 的列
        if self.config['bombcell']['remove_nan_columns']:
            nan_cols = bc_qm_df.columns[bc_qm_df.isna().all()].tolist()
            if nan_cols:
                self.logger.info(f"删除 {len(nan_cols)} 个全为 NaN 的列")
                bc_qm_df = bc_qm_df.drop(columns=nan_cols)
        
        # 加载波形数据
        waveform = np.load(self.bc_path / 'templates._bc_rawWaveforms.npy')
        max_channels = np.load(self.bc_path / 'templates._bc_rawWaveformPeakChannels.npy')
        
        # 准备保存的波形
        saved_waveform, waveform_channels = self._prepare_waveforms(waveform, max_channels)
        
        # 加载 unit 类型
        bc_results_file = self.bc_path / 'bombcell_results.json'
        with open(bc_results_file, 'r', encoding='utf-8') as f:
            bc_data = json.load(f)
        bc_unittype = bc_data['unitType']
        
        # 写入 NWB 文件
        with NWBHDF5IO(self.nwbfile_path, 'r+') as io:
            nwbfile = io.read()
            
            # 添加列
            self._add_unit_columns(nwbfile, bc_qm_df)
            
            # 添加 units
            self._add_units(
                nwbfile, n_units, spike_times_list, trial_df,
                bc_unittype, bc_unittype_string, bc_qm_df,
                spike_pos, spike_template, saved_waveform, waveform_channels
            )
            
            io.write(nwbfile)
        
        self.logger.info("✓ Step 4 完成: 自定义 units 已添加")
        
    def _prepare_waveforms(self, waveform, max_channels):
        """准备保存的波形数据"""
        wf_config = self.config['units']['waveform']
        n_channels_around = wf_config['n_channels_around']
        total_channels = wf_config['total_channels']
        
        saved_waveform = []
        waveforms_channels = []
        for max_channel in max_channels:
            near_channels = np.linspace(
                -n_channels_around, n_channels_around,
                endpoint=True, num=2 * n_channels_around + 1
            ) + max_channel
            saved_channels = np.intersect1d(
                near_channels, np.arange(total_channels)
            ).astype(np.int16)
            saved_waveform.append(waveform[:, saved_channels, :])
            waveforms_channels.append(saved_channels)
        
        return saved_waveform, waveforms_channels
        
    def _add_unit_columns(self, nwbfile, bc_qm_df):
        """添加 unit 列"""
        # 添加自定义列
        custom_cols = self.config['units']['custom_columns']
        for col_name, col_info in custom_cols.items():
            nwbfile.add_unit_column(
                name=col_name,
                description=col_info['description'],
                data=[]
            )
        
        # 添加 Bombcell 质量指标列
        if self.config['bombcell']['add_quality_metrics']:
            add_bombcell_columns_to_nwb(nwbfile, bc_qm_df)
        
        self.logger.info(f"添加了 {len(custom_cols)} 个自定义列 + Bombcell 质量指标列")
        
    def _add_units(self, nwbfile, n_units, spike_times_list, trial_df,
                  bc_unittype, bc_unittype_string, bc_qm_df,
                  spike_pos, spike_template, saved_waveform, waveform_fromch):
        """添加 units"""
        # 获取配置
        raster_config = self.config['units']['raster']
        filter_config = self.config['units']['filtering']
        
        # 转换时间窗口（毫秒 -> 秒）
        pre_onset = raster_config['pre_onset_ms'] / 1000
        post_onset = raster_config['post_onset_ms'] / 1000
        baseline_window = [x / 1000 for x in raster_config['baseline_window_ms']]
        response_window = [x / 1000 for x in raster_config['response_window_ms']]
        bin_size_s = raster_config['bin_size_ms'] / 1000
        
        # 统计信息
        units_added = 0
        units_filtered = 0
        
        show_progress = self.config.get("logging", {}).get("show_progress", True)
        iterator = tqdm(range(n_units), desc="添加 units") if show_progress else range(n_units)
        
        for i_unit in iterator:
            # 计算响应
            epoch_raster, baseline_spikes, response_spikes = self._compute_unit_response(
                spike_times_list[i_unit], trial_df,
                pre_onset, post_onset, baseline_window, response_window, bin_size_s
            )
            
            # 统计检验
            if filter_config['enable_statistical_test']:
                passed_test = self._statistical_test(
                    baseline_spikes, response_spikes, filter_config
                )
            else:
                passed_test = True
            
            # 检查 Bombcell unittype
            if filter_config['exclude_bombcell_zero'] and bc_unittype[i_unit] == 0:
                passed_test = False
            
            # 如果通过筛选，添加 unit
            if passed_test:
                unit_kwargs = self._prepare_unit_kwargs(
                    i_unit, spike_times_list[i_unit], epoch_raster,
                    bc_unittype, bc_unittype_string, bc_qm_df,
                    spike_pos, spike_template, saved_waveform, waveform_fromch
                )
                
                nwbfile.add_unit(**unit_kwargs)
                units_added += 1
            else:
                units_filtered += 1
        
        self.logger.info(f"添加了 {units_added} 个 units，过滤了 {units_filtered} 个 units")
        
    def _compute_unit_response(self, spike_times, trial_df,
                               pre_onset, post_onset, baseline_window,
                               response_window, bin_size_s):
        """计算单个 unit 的响应"""
        epoch_raster = []
        baseline_spikes = []
        response_spikes = []
        
        for index, trial in trial_df.iterrows():
            if trial['fix_success']:
                event_time = trial['start_time']
                
                # 定义时间窗口
                epoch_start = event_time - pre_onset
                epoch_end = event_time + post_onset
                
                # 筛选放电
                indices = np.where(
                    (spike_times >= epoch_start) & (spike_times <= epoch_end)
                )[0]
                spikes_in_epoch = spike_times[indices]
                
                # 对齐到事件时间
                aligned_spikes = spikes_in_epoch - event_time
                
                # Baseline 放电
                baseline_indices = np.where(
                    (aligned_spikes >= baseline_window[0]) &
                    (aligned_spikes < baseline_window[1])
                )[0]
                baseline_spikes.append(len(aligned_spikes[baseline_indices]))
                
                # Response 放电
                response_indices = np.where(
                    (aligned_spikes >= response_window[0]) &
                    (aligned_spikes < response_window[1])
                )[0]
                response_spikes.append(len(aligned_spikes[response_indices]))
                
                # 计算 raster
                bins = np.arange(-pre_onset, post_onset + bin_size_s, bin_size_s)
                raster, _ = np.histogram(aligned_spikes, bins=bins)
                epoch_raster.append(raster)
        
        epoch_raster = np.array(epoch_raster).astype(np.uint8)
        
        return epoch_raster, baseline_spikes, response_spikes
        
    def _statistical_test(self, baseline_spikes, response_spikes, filter_config):
        """执行统计检验"""
        test_method = filter_config['statistical_test']
        p_threshold = filter_config['p_value_threshold']
        alternative = filter_config['alternative']
        
        if test_method == 'mannwhitneyu':
            _, p = mannwhitneyu(
                baseline_spikes, response_spikes,
                alternative=alternative,
                method='auto'
            )
        else:
            raise ValueError(f"不支持的统计检验方法: {test_method}")
        
        return p < p_threshold
        
    def _prepare_unit_kwargs(self, i_unit, spike_times, epoch_raster,
                            bc_unittype, bc_unittype_string, bc_qm_df,
                            spike_pos, spike_template, saved_waveform, waveform_fromch):
        """准备 unit 的参数"""
        # 计算 unit 位置
        unitpos = spike_pos[np.where(spike_template == i_unit)[0], :].mean(axis=0)
        
        # 将 waveform_fromch 转换为字符串，避免ragged array问题
        # PyNWB 不能直接处理长度不同的数组
        waveform_channels_str = ','.join(map(str, waveform_fromch[i_unit].astype(int)))
        
        unit_kwargs = {
            'spike_times': spike_times,
            'ks_id': int(i_unit),
            'unitpos': unitpos,
            'unittype': int(bc_unittype[i_unit]),
            'unittype_string': str(bc_unittype_string[i_unit]),
            'waveforms': saved_waveform[i_unit],
            'waveforms_fromch': waveform_channels_str,
            'Raster': epoch_raster
        }
        
        # 添加 Bombcell 质量指标
        if self.config['bombcell']['add_quality_metrics']:
            bc_metrics = get_bombcell_metrics_for_unit(bc_qm_df, i_unit)
            unit_kwargs.update(bc_metrics)
        
        return unit_kwargs
        
    def run_full_pipeline(self, output_filename: Optional[str] = None):
        """
        运行完整的数据整合流程
        
        Args:
            output_filename: 输出文件名（可选）
        """
        self.logger.info("开始完整的数据整合流程")
        self.logger.info("=" * 60)
        
        try:
            # Step 1: 转换原始数据
            self.step1_convert_raw_data(output_filename)
            
            # Step 2: 添加 Kilosort 结果
            self.step2_add_kilosort_results()
            
            # Step 3: 添加行为数据
            self.step3_add_behavioral_data()
            
            # Step 4: 添加自定义 units
            self.step4_add_custom_units()
            
            self.logger.info("=" * 60)
            self.logger.info(f"✓ 数据整合完成！")
            self.logger.info(f"输出文件: {self.nwbfile_path}")
            self.logger.info("=" * 60)
            
            return self.nwbfile_path
            
        except Exception as e:
            self.logger.error(f"数据整合过程中出错: {e}", exc_info=True)
            raise


# 便捷函数
def integrate_data(data_path: Union[str, Path],
                  info_yaml: Optional[Union[str, Path]] = None,
                  output_folder: Optional[Union[str, Path]] = None,
                  target_area: Optional[str] = None,
                  config_path: Optional[Union[str, Path]] = None) -> Path:
    """
    便捷函数：运行完整的数据整合流程
    
    Args:
        data_path: 项目根目录路径
        info_yaml: 受试者配置文件路径（例如 "MaoDan.yaml"）
        output_folder: 输出文件夹路径
        electrode_location: 电极位置（例如 "MLO"）
        config_path: 配置文件路径
        
    Returns:
        输出的 NWB 文件路径
    """
    integrator = DataIntegrator(
        data_path=data_path,
        config_path=config_path,
        info_yaml=info_yaml,
        output_folder=output_folder,
        target_area=target_area
    )
    
    return integrator.run_full_pipeline()
