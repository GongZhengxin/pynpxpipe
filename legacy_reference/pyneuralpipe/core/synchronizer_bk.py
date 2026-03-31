"""
同步与校验模块

负责对齐神经数据与行为数据的时间戳，校准刺激呈现时间
完全复现MATLAB Load_Data_function.m的处理流程
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非交互式后端，适合Streamlit
from typing import Dict, Any, Optional, Tuple, List
from scipy import signal, interpolate
from scipy.stats import pearsonr, zscore
from fractions import Fraction
from pathlib import Path
import io
import base64

from utils.logger import ProcessLogger
from utils.error_handler import ProcessingError, ValidationError, error_boundary
from utils.config_manager import get_config_manager


class DataSynchronizer:
    """
    数据同步器类 - 完全复现MATLAB Load_Data_function.m处理流程
    
    负责神经数据与行为数据的时间同步、校验、可视化和数据导出
    """
    
    def __init__(self, data_loader):
        """
        初始化数据同步器
        
        Args:
            data_loader: DataLoader类的实例，包含所有数据
        """
        self.data_loader = data_loader
        self.logger = ProcessLogger()
        
        # 获取配置管理器和配置
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_synchronizer_config()
        
        # 从配置获取同步器参数
        self.eye_tracking_config = self.config.get('eye_tracking', {})
        self.photodiode_config = self.config.get('photodiode', {})
        self.sync_validation_config = self.config.get('sync_validation', {})
        
        # 从data_loader获取数据引用
        self.neural_data = data_loader.get_spikeglx_data()
        self.behavior_data = data_loader.get_monkeylogic_data()  
        self.sync_data = data_loader.get_sync_data()
        self.data_path = data_loader.data_path
        
        # 处理结果存储
        self.sync_line = None
        self.onset_times_ml = 0
        self.onset_times_sglx = 0
        self.valid_eye_count = 0
        self.trial_valid_idx = None
        self.dataset_valid_idx = None
        self.onset_time_ms = None
        self.eye_matrix = None
        self.dataset_name = None
        self.imgset_size = 0
        self.h5_file = self.data_path / 'processed' / f'META_{self.data_path.name}.h5'
        # 可视化图表存储
        self.visualizations = {}
        
        # 从配置文件加载参数（保持向后兼容的默认值）
        self.params = {
            'eye_threshold': self.eye_tracking_config.get('threshold', 0.999),
            'before_onset_measure': self.photodiode_config.get('before_onset_measure', 10),  # ms
            'after_onset_measure': self.photodiode_config.get('after_onset_measure', 50),   # ms
            'after_onset_stats': self.photodiode_config.get('after_onset_stats', 100),    # ms
            'monitor_delay_correction': self.photodiode_config.get('monitor_delay_correction', -5),  # ms
            'threshold_baseline_weight': self.photodiode_config.get('threshold_baseline_weight', 0.1),
            'threshold_peak_weight': self.photodiode_config.get('threshold_peak_weight', 0.9),
            'highline_detection_window': self.photodiode_config.get('highline_detection_window', 20),
            'max_time_error': self.sync_validation_config.get('max_time_error', 17),
        }
        
        self.logger.log_info(f"同步器参数已从配置加载: {self.params}")
        
        # 处理状态
        self.processing_complete = False
        self.export_data = {}
    
    @error_boundary("完整同步处理")
    def process_full_synchronization(self) -> bool:
        """
        执行完整的同步处理流程，复现MATLAB Load_Data_function.m
        
        Returns:
            是否成功完成处理
        """
        step_idx = self.logger.start_step("process_full_synchronization", "开始完整同步处理流程")
        
        try:
            # 1. 准备同步数据（复现MATLAB同步检查）
            self.logger.log_info("步骤1: 准备并检查设备间同步")
            self._prepare_sync_data()
            
            # 2. 检查ML和NI对齐（复现MATLAB onset统计）
            self.logger.log_info("步骤2: 检查MonkeyLogic和NI设备对齐")
            self._check_ml_ni_alignment()
            
            # 3. 提取数据集信息
            self.logger.log_info("步骤3: 提取数据集信息")
            self._extract_dataset_info()
            
            # 4. 眼动验证和试次筛选
            self.logger.log_info("步骤4: 眼动验证和试次筛选")
            self._validate_eye_tracking()
            
            # 5. 光敏二极管时间校准
            self.logger.log_info("步骤5: 光敏二极管时间校准")
            self._calibrate_photodiode_timing()
            
            # 6. 生成可视化图表
            self.logger.log_info("步骤6: 生成数据检查可视化")
            self._generate_visualizations()
            
            # 7. 准备导出数据
            self.logger.log_info("步骤7: 准备导出数据")
            self._prepare_export_data()

            # 8. 导出数据到HDF5文件
            self.logger.log_info("步骤8: 导出数据到HDF5文件")
            self._export_data_to_hdf5()
            self.processing_complete = True
            self.logger.complete_step(step_idx, True, "完整同步处理流程完成")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ProcessingError(f"同步处理失败: {str(e)}")
    
    def _prepare_sync_data(self):
        """准备同步数据，复现examine_and_fix_sync.m"""
        try:
            # 从配置获取采样率默认值
            spikeglx_config = self.data_loader.config.get('spikeglx', {})
            sampling_rates = spikeglx_config.get('sampling_rates', {})
            
            # 准备IMEC数据
            imSampRate = float(self.sync_data['imec_meta'].get('imSampRate', sampling_rates.get('imec_default', 30000)))
            Dcode_imec_all = np.diff(np.squeeze(self.sync_data['imec_sync']))
            
            self.Dcode_imec = {
                'CodeLoc': np.where(Dcode_imec_all > 0)[0],
                'CodeVal': Dcode_imec_all[np.where(Dcode_imec_all > 0)[0]],
                'CodeTime': 1000 * np.where(Dcode_imec_all > 0)[0] / imSampRate
            }
            
            # 统计IMEC事件
            for code in np.unique(self.Dcode_imec['CodeVal']):
                sum_times = np.sum(self.Dcode_imec['CodeVal'] == code)
                self.logger.log_info(f'IMEC Event {code} : {sum_times} Times')
            
            # 准备NI数据
            niSampRate = float(self.sync_data['nidq_meta'].get('niSampRate', 30000))
            Dcode_ni_all = np.diff(np.squeeze(self.sync_data['nidq_digital']))
            
            self.Dcode_ni = {
                'CodeLoc': np.where(Dcode_ni_all != 0)[0] + 1,
                'CodeVal': np.squeeze(self.sync_data['nidq_digital'])[np.where(Dcode_ni_all != 0)[0] + 1],
                'CodeTime': 1000 * (np.where(Dcode_ni_all != 0)[0] + 1) / niSampRate
            }
            
            # 插入初始值
            self.Dcode_ni['CodeVal'] = np.insert(self.Dcode_ni['CodeVal'], 0, 0)
            
            # 从配置获取数字通道映射
            digital_channel_map = self.sync_data.get('digital_channel_map', {})
            
            # 统计NI事件
            for code in range(8):
                bit_mask = 1 << code
                sum_times = np.sum(np.diff(self.Dcode_ni['CodeVal'] & bit_mask) > 0)
                
                # 查找对应的通道名称
                channel_name = None
                for name, bit_num in digital_channel_map.items():
                    if bit_num == code:
                        channel_name = name
                        break
                
                if channel_name:
                    self.logger.log_info(f'NI Event {bit_mask} ({channel_name}) : {sum_times} Times')
                else:
                    self.logger.log_info(f'NI Event {bit_mask} : {sum_times} Times')
            
            # 执行同步检查（使用配置中的同步通道）
            sync_bit = digital_channel_map.get('sync', 0)
            ni_sync_loc = np.where(np.diff(self.Dcode_ni['CodeVal'] & (1 << sync_bit)) > 0)[0]
            ni_sync_time = self.Dcode_ni['CodeTime'][ni_sync_loc]
            imec_sync_loc = np.where(self.Dcode_imec['CodeVal'] == 64)[0]
            imec_sync_time = self.Dcode_imec['CodeTime'][imec_sync_loc]
            
            # 验证同步质量
            max_time_error = self.params['max_time_error']
            
            if len(ni_sync_time) == len(imec_sync_time):
                time_err = ni_sync_time - imec_sync_time
                mean_error = np.mean(time_err)
                max_error = np.max(np.abs(time_err))
                
                if max_error <= max_time_error:
                    sync_status = 'success'
                    self.logger.log_info(f"同步成功: {len(ni_sync_time)}个事件, 平均误差: {mean_error:.3f}ms, 最大误差: {max_error:.3f}ms")
                else:
                    sync_status = 'warning'
                    self.logger.log_warning(f"同步质量警告: 最大误差 {max_error:.3f}ms 超过阈值 {max_time_error}ms")
                
                self.sync_line = {
                    'ni_sync_time': ni_sync_time,
                    'imec_sync_time': imec_sync_time,
                    'ni_events': len(ni_sync_time),
                    'imec_events': len(imec_sync_time),
                    'time_errors': time_err,
                    'mean_error': mean_error,
                    'max_error': max_error,
                    'status': sync_status
                }
            else:
                self.logger.log_warning(f"同步失败: NI={len(ni_sync_time)}, IMEC={len(imec_sync_time)}")
                self.sync_line = {'status': 'failed', 'ni_events': len(ni_sync_time), 'imec_events': len(imec_sync_time)}
                
        except Exception as e:
            self.logger.log_error(f"同步数据准备失败: {str(e)}")
            raise
    
    def _check_ml_ni_alignment(self):
        """检查MonkeyLogic和NI设备对齐，复现MATLAB统计逻辑"""
        try:
            # 从配置获取代码映射
            data_loader_config = self.config.get('data_loader', {})
            ml_config = data_loader_config.get('monkeylogic', {})
            code_mappings = ml_config.get('code_mappings', {})
            
            # 从配置获取onset和offset代码，回退到默认值
            stim_onset_code = code_mappings.get('stim_onset', 64)
            stim_offset_code = code_mappings.get('stim_offset', 32)
            
            
            # 统计ML中的onset和offset
            ML_num_trials = self.behavior_data.get('num_trials', 0)
            self.onset_times_ml = 0
            offset_times = 0
            onset_times_by_trial_ML = np.zeros(ML_num_trials)

            ML_codenumbers = self.behavior_data['BehavioralCodes']['CodeNumbers']
            self.onset_times_ml = np.sum([np.sum(ML_code==stim_onset_code) for ML_code in ML_codenumbers])
            offset_times = np.sum([np.sum(ML_code==stim_offset_code) for ML_code in ML_codenumbers])
            
            onset_times_by_trial_ML = np.array([np.sum(ML_code==stim_onset_code) for ML_code in ML_codenumbers])

            self.logger.log_info(f'MonkeyLogic Has {ML_num_trials} trials {self.onset_times_ml} onset (code {stim_onset_code}) {offset_times} offset (code {stim_offset_code})')
            
            # 从配置获取数字通道映射
            spikeglx_config = data_loader_config.get('spikeglx', {})
            digital_channel_map = spikeglx_config.get('digital_channel_map', {})
            trial_start_bit = digital_channel_map.get('trial_start', 1)
            stim_onset_bit = digital_channel_map.get('stim_onset', 6)
            
            # 统计SGLX中的onset
            NI_trialloc = np.where(np.diff(self.Dcode_ni['CodeVal'] & (1 << trial_start_bit)) > 0)[0] + 1
            num_trial = len(NI_trialloc)

            # check trial code
            if num_trial != ML_num_trials:
                self.logger.log_warning(f'Inconsistent Trial Number: [NI has {num_trial} trials] != [ML has {ML_num_trials} trials]')
                fixed = False
                # auto fix
                for bit_code in range(8):
                    new_code = 1 << bit_code
                    trial_num_by_code_fixed = np.sum(np.diff(self.Dcode_ni['CodeVal'] & (new_code)) > 0)
                    if trial_num_by_code_fixed == ML_num_trials and new_code != 16:
                        self.logger.log_info(f'Auto fix trial code: {new_code}')
                        NI_trialloc = np.where(np.diff(self.Dcode_ni['CodeVal'] & (new_code)) > 0)[0] + 1
                        trial_start_bit = bit_code
                        fixed = True
                        break
                if not fixed:
                    self.logger.log_warning(f'NI trial 事件 与 ML trial 事件不一致, 且无法自动修复（非trigger code mapping原因）')
                    self.logger.log_warning(f'可能原因1: SpikeGLX 比 MonkeyLogic 开晚了或关早了')
                    self.logger.log_warning(f'可能原因2: MonkeyLogic 文件拷贝错了')
                    raise ProcessingError(f'Failed to auto fix trial code')

            NI_trialloc = np.insert(NI_trialloc, num_trial, len(self.Dcode_ni['CodeVal']))

            onset_times_by_trial_SGLX = np.array([np.sum(np.diff(self.Dcode_ni['CodeVal'][NI_trialloc[_]:NI_trialloc[_+1]] & (1 << stim_onset_bit)) > 0) for _ in range(num_trial)])
                        
            self.onset_times_sglx = int(np.sum(onset_times_by_trial_SGLX))
            
            # 检查一致性
            max_err = np.max(onset_times_by_trial_ML - onset_times_by_trial_SGLX)
            if max_err > 0:
                err_Trials = np.where((onset_times_by_trial_ML - onset_times_by_trial_SGLX) != 0)[0]
                self.logger.log_warning(f'Inconsistent Stimulus Number in Trials: {err_Trials + 1}')
                self.logger.log_warning(f'可能原因1: MonkeyLogic 文件拷贝错了,只是恰好匹配了ML的试次')
                self.logger.log_warning(f'可能原因2: 有 onset trigger 漏发了, 麻烦大了')
            
            self.logger.log_info(f'SGLX onset count: {self.onset_times_sglx} (bit {stim_onset_bit}), MaxErr: {max_err}')
            
            # 存储对比数据供可视化使用
            self.onset_comparison = {
                'ml_by_trial': onset_times_by_trial_ML,
                'sglx_by_trial': onset_times_by_trial_SGLX,
                'max_error': max_err,
                'code_mappings': {
                    'stim_onset_code': stim_onset_code,
                    'stim_offset_code': stim_offset_code,
                    'trial_start_bit': trial_start_bit,
                    'stim_onset_bit': stim_onset_bit
                }
            }
            
        except Exception as e:
            self.logger.log_error(f"ML-NI对齐检查失败: {str(e)}")
            raise
    
    def _extract_dataset_info(self):
        """提取数据集信息，确定刺激集名称"""
        try:
            # 获取数据集名称
            dataset_names = self.behavior_data['UserVars'].get('DatasetName', [])
            datasets = np.unique([name for name in dataset_names if name is not None])
            
            if len(datasets) > 0:
                dataset_path = Path(datasets[0])
                self.dataset_path = dataset_path
                self.dataset_name = dataset_path.name.split('.')[0]
                self.logger.log_info(f"数据集名称: {self.dataset_name}")
            else:
                self.dataset_name = "unknown_dataset"
                self.logger.log_warning("未找到数据集名称，使用默认值")
                
        except Exception as e:
            self.logger.log_error(f"数据集信息提取失败: {str(e)}")
            self.dataset_name = "unknown_dataset"
    
    def _validate_eye_tracking(self):
        """眼动追踪验证，复现for_sync.md的简洁逻辑"""
        try:
            # 初始化变量，使用for_sync.md的命名
            onset_times = int(self.onset_times_ml)
            valid_stim_idx = np.zeros(onset_times)
            valid_dataset_idx = np.zeros(onset_times)
            stim_global_idx = 0
            
            # 获取数据，使用for_sync.md的变量名
            ML_stimons = self.behavior_data['VariableChanges']['onset_time']
            ML_codenumbers = self.behavior_data['BehavioralCodes']['CodeNumbers']
            ML_codetimes = self.behavior_data['BehavioralCodes']['CodeTimes']
            ML_imagetrian = self.behavior_data["UserVars"]["Current_Image_Train"]
            ML_datasetname = self.behavior_data['UserVars']['DatasetName']
            ML_sampleinterv = self.behavior_data['AnalogData']['SampleInterval']
            ML_eyedata = self.behavior_data['AnalogData']['Eye']
            ML_fixwindow = self.behavior_data['VariableChanges']['fixation_window']
            
            # 获取数据集列表
            datasets = np.unique([name for name in ML_datasetname if name is not None]).tolist()
            
            # 确定eye_matrix维度
            stim_ondurs = np.unique([dur for dur in ML_stimons if dur is not None])
            max_dur = int(stim_ondurs[0]) if len(stim_ondurs) == 1 else int(np.max(stim_ondurs))
            if len(stim_ondurs) == 1:
                eye_matrix = np.nan * np.zeros((onset_times, max_dur, 2))
            else:
                eye_matrix = np.nan * np.zeros((onset_times, max_dur, 2))
            
            # 眼动验证阈值
            ratio_threshold = self.params['eye_threshold']
            num_trial = self.behavior_data.get('num_trials', 0)
            
            self.stim_ondurs = []
            # 主循环：逐试次处理
            for i_trial in range(num_trial):
                if i_trial >= len(ML_stimons) or ML_stimons[i_trial] is None:
                    continue
                    
                stim_ondur = ML_stimons[i_trial]
                stim_onset_loc = np.where(ML_codenumbers[i_trial] == 64)[0]
                if len(stim_onset_loc) == 0:
                    continue
                
                cur_imagetrian = ML_imagetrian[i_trial][0:len(stim_onset_loc)]
                
                # 确定数据集索引
                if i_trial < len(ML_datasetname) and ML_datasetname[i_trial] in datasets:
                    dataset_idx = datasets.index(ML_datasetname[i_trial]) + 1
                else:
                    dataset_idx = 1
                
                # 处理每个刺激onset
                for stim_idx in range(len(stim_onset_loc)):
                    stim_start_time = ML_codetimes[i_trial][stim_onset_loc[stim_idx]]
                    stim_end_time = stim_start_time + stim_ondur
                    self.stim_ondurs.append(stim_ondur)
                    # 计算眼动数据时间索引
                    stim_start2end = np.floor(
                            np.arange(stim_start_time, stim_end_time) / ML_sampleinterv[i_trial]
                        ).astype(np.int16)
                    try:
                        # 提取眼动数据
                        stim_start2end = stim_start2end[0:stim_ondur]
                        eye_data = ML_eyedata[i_trial][stim_start2end]
                    except IndexError:
                        max_index = ML_eyedata[i_trial].shape[0] - 1
                        stim_start2end[np.where(stim_start2end>=max_index)] = max_index
                        stim_start2end = stim_start2end[0:stim_ondur]
                        eye_data = ML_eyedata[i_trial][stim_start2end]
                    # 计算眼动距离
                    eye_distance = np.linalg.norm(eye_data, axis=1)
                    
                    # 计算眼动有效比例
                    eye_valid_ratio = np.sum(eye_distance < ML_fixwindow[i_trial]) / stim_ondur
                    
                    # 验证眼动质量
                    if eye_valid_ratio > ratio_threshold:
                        valid_dataset_idx[stim_global_idx] = dataset_idx
                    valid_stim_idx[stim_global_idx] = cur_imagetrian[stim_idx]
                    # 存储眼动数据
                    eye_matrix[stim_global_idx, 0:stim_ondur, :] = eye_data
                    stim_global_idx += 1
            
            # 保存结果，保持接口兼容
            self.trial_valid_idx = valid_stim_idx
            self.dataset_valid_idx = valid_dataset_idx
            self.eye_matrix = eye_matrix
            self.valid_eye_count = int(np.sum(valid_stim_idx > 0))
            
            # 计算图像数量
            valid_stim = valid_stim_idx[valid_dataset_idx > 0]
            self.imgset_size = int(np.max(valid_stim)) if len(valid_stim) > 0 else 0
            
            self.logger.log_info(f"眼动验证完成: {self.valid_eye_count}个有效onset, 图像数量: {self.imgset_size}")
            
        except Exception as e:
            self.logger.log_error(f"眼动验证失败: {str(e)}")
            raise
    
    def _calibrate_photodiode_timing(self):
        """光敏二极管时间校准，复现for_sync.md的简洁逻辑"""
        try:
            # 获取NI模拟信号并转换，使用for_sync.md的变量名
            niAiRangeMax = int(self.sync_data['nidq_meta'].get('niAiRangeMax', 5))
            niSampRate = float(self.sync_data['nidq_meta'].get('niSampRate', 30000))
            fI2V = niAiRangeMax / 32768
            AIN = self.sync_data['nidq_analog'] * fI2V
            
            # 重采样到1ms
            ratio = 1000 / niSampRate
            frac = Fraction(ratio).limit_denominator()
            p = frac.numerator
            q = frac.denominator
            AIN = np.squeeze(signal.resample_poly(AIN, p, q))
            
            # 找到刺激onset位置
            before_onset_measure = self.params['before_onset_measure']
            after_onset_measure = self.params['after_onset_measure']
            after_onset_stats = self.params['after_onset_stats']
            
            # 从配置获取刺激onset位
            data_loader_config = self.config.get('data_loader', {})
            spikeglx_config = data_loader_config.get('spikeglx', {})
            digital_channel_map = spikeglx_config.get('digital_channel_map', {})
            stim_onset_bit = digital_channel_map.get('stim_onset', 6)
            
            onset_LOC = np.where(np.diff(self.Dcode_ni['CodeVal'] & (1 << stim_onset_bit)) > 0)[0]
            stim_onset_ms = np.floor(self.Dcode_ni['CodeTime'][onset_LOC]).astype(np.int64)
            start_times = stim_onset_ms - before_onset_measure
            end_times = stim_onset_ms + after_onset_stats
            
            # 提取并z-score标准化信号
            photodoide = np.array([zscore(AIN[start_time:end_time]) 
                                 for start_time, end_time in zip(start_times, end_times)])
            
            # 从配置获取阈值计算参数
            baseline_weight = self.params['threshold_baseline_weight']
            peak_weight = self.params['threshold_peak_weight']
            peak_window = self.params['highline_detection_window']
            
            # 计算阈值
            baseline = photodoide[:, :before_onset_measure].mean()
            time_lag = before_onset_measure + after_onset_measure
            highline = photodoide[:, np.arange(peak_window) + time_lag].mean()
            threshold = baseline_weight * baseline + peak_weight * highline
            
            # 计算onset延迟（使用for_sync.md的简洁方式）
            
            onset_latency = np.array([
                np.where(photodoide[_, :] > threshold)[0].min() - before_onset_measure 
                if len(np.where(photodoide[_, :] > threshold)[0]) > 0 else np.nan
                for _ in range(photodoide.shape[0])
            ])
            if np.isnan(onset_latency).any():
                err_stim_onset = np.where(np.isnan(onset_latency))[0]
                self.logger.log_warning(f'存在未达到阈值的Photodiode信号')
                self.logger.log_warning(f'可能原因1: ML 中关于 PhotoDoide 的设置错了')
                self.logger.log_warning(f'可能原因2: PhotoDoide 信号接收有问题，比如固定在屏幕上的黑胶带松了')
                raise ProcessingError(f'光敏二极管校准失败: 在第 {err_stim_onset + 1} 张图片试次中，Photodiode 信号未达到阈值')
            
            # 应用延迟校正
            stim_onset_ms = stim_onset_ms + onset_latency
            
            # 应用显示器延迟校正
            stim_onset_ms = stim_onset_ms + self.params['monitor_delay_correction']
            
            # 校准后的光敏二极管信号
            start_times = stim_onset_ms - before_onset_measure
            end_times = stim_onset_ms + after_onset_stats
            
            calibrated_photodoide = np.array([zscore(AIN[start_time:end_time]) 
                                           for start_time, end_time in zip(start_times, end_times)])
            
            # 保存校准结果
            self.calibrated_photodiode = calibrated_photodoide
            
            # 有效试次的校准信号
            valid_calibrated_photodoide = calibrated_photodoide[self.dataset_valid_idx[:len(calibrated_photodoide)] > 0, :]
            self.valid_calibrated_photodiode = valid_calibrated_photodoide
            
            # 存储校准后的onset时间
            # 将刺激时间 对齐到 神经数据时间
            stim_onset_ms = np.interp(stim_onset_ms, self.sync_line['ni_sync_time'], self.sync_line['imec_sync_time'])
            self.onset_time_ms = stim_onset_ms
            self.stim_end_times = stim_onset_ms + np.array(self.stim_ondurs)

            self.logger.log_info(f"光敏二极管校准完成: {len(self.onset_time_ms)}个onset, "
                               f"延迟范围: {np.min(onset_latency):.1f}~{np.max(onset_latency):.1f}ms")
            
        except Exception as e:
            self.logger.log_error(f"光敏二极管校准失败: {str(e)}")
            raise
    
    def _generate_visualizations(self):
        """生成所有可视化图表，复现MATLAB figure"""
        try:
            # 创建主图像 (3x6 subplots)
            fig = plt.figure(figsize=(18, 9))
            
            # 1. Onset times scatter plot
            ax1 = plt.subplot(3, 6, 1)
            if hasattr(self, 'onset_comparison'):
                ml_trials = self.onset_comparison['ml_by_trial']
                sglx_trials = self.onset_comparison['sglx_by_trial']
                min_len = min(len(ml_trials), len(sglx_trials))
                
                plt.scatter(sglx_trials[:min_len], ml_trials[:min_len])
                plt.xlabel('onset times SGLX')
                plt.ylabel('onset times ML')
                plt.title(f'MaxErr={self.onset_comparison["max_error"]:.0f}')
            
            # 2. 原始光敏二极管信号
            if hasattr(self, 'calibrated_photodiode'):
                ax2 = plt.subplot(3, 6, 2)
                before_onset = self.params['before_onset_measure']
                after_onset = self.params['after_onset_stats']
                
                plt.imshow(self.calibrated_photodiode, aspect='auto', 
                         extent=[-before_onset, after_onset, 1, len(self.calibrated_photodiode)])
                plt.xlabel('Time ms')
                plt.ylabel('Trial')
                plt.title('Calibrated Signal')
            
            # 7. 校准后的平均信号
            if hasattr(self, 'calibrated_photodiode'):
                ax7 = plt.subplot(3, 6, 7)
                mean_signal = np.mean(self.calibrated_photodiode, axis=0)
                std_signal = np.std(self.calibrated_photodiode, axis=0)
                time_axis = np.arange(len(mean_signal)) - before_onset
                
                plt.plot(time_axis, mean_signal, 'b-', linewidth=2)
                plt.fill_between(time_axis, mean_signal - std_signal, mean_signal + std_signal, alpha=0.3)
                plt.xlabel('time from event')
                plt.title('After time calibration')
                plt.grid(True, alpha=0.3)
            
            # 9. 排除非注视试次后的信号
            if hasattr(self, 'valid_calibrated_photodiode'):
                ax9 = plt.subplot(3, 6, 9)
                if len(self.valid_calibrated_photodiode) > 0:
                    mean_signal = np.mean(self.valid_calibrated_photodiode, axis=0)
                    std_signal = np.std(self.valid_calibrated_photodiode, axis=0)
                    time_axis = np.arange(len(mean_signal)) - before_onset
                    
                    plt.plot(time_axis, mean_signal, 'g-', linewidth=2)
                    plt.fill_between(time_axis, mean_signal - std_signal, mean_signal + std_signal, alpha=0.3)
                    plt.xlabel('time from event')
                    plt.title('Exclude Non-Look Trial')
                    plt.grid(True, alpha=0.3)
            
            # 11. 刺激重复次数
            if hasattr(self, 'trial_valid_idx') and self.imgset_size > 0:
                ax11 = plt.subplot(3, 6, 11)
                valid_stim = self.trial_valid_idx[self.trial_valid_idx > 0]
                if len(valid_stim) > 0:
                    unique_stim, counts = np.unique(valid_stim, return_counts=True)
                    plt.plot(unique_stim, counts, 'o-')
                    plt.xlim([1, self.imgset_size])
                    plt.ylim([0, np.max(counts) + 1])
                    plt.xlabel('Stimuli Idx')
                    plt.ylabel('Number of trials')
            
            # 12. 眼动位置密度图
            if hasattr(self, 'eye_matrix'):
                ax12 = plt.subplot(3, 6, 12)
                plot_eye = np.nanmean(self.eye_matrix, axis=1)
                
                # 创建bin范围
                binx = np.arange(-8, 8.5, 0.5)
                biny = np.arange(-8, 8.5, 0.5)
                
                # 提取有效的x和y坐标
                valid_mask = ~np.isnan(plot_eye).any(axis=1)
                if np.sum(valid_mask) > 0:
                    x = plot_eye[valid_mask, 0]
                    y = plot_eye[valid_mask, 1]
                    
                    # 生成二维直方图
                    density_plot, xedges, yedges = np.histogram2d(x, y, bins=[binx, biny])
                    density_plot_log = np.where(density_plot > 0, np.log10(density_plot + 1e-10), np.nan)
                    
                    plt.imshow(density_plot_log.T, extent=[binx[0]-0.15, binx[-1]-0.15, 
                                                         biny[0]-0.15, biny[-1]-0.15], 
                             origin='lower', aspect='auto')
                    plt.xlabel('Eyex')
                    plt.ylabel('Eyey')
            
            plt.suptitle(f"Data Check - {self.data_path.name}", fontsize=16)
            plt.tight_layout()
            
            # 保存图像
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            
            # 转换为base64供Streamlit显示
            img_base64 = base64.b64encode(buf.read()).decode()
            self.visualizations['data_check'] = img_base64
            
            plt.close()
            
            # 生成同步误差图
            if hasattr(self, 'sync_line') and self.sync_line['status'] == 'success':
                fig_sync = plt.figure(figsize=(6, 4))
                plt.plot(self.sync_line['time_errors'], linewidth=0.5)
                plt.xlabel('Event Index')
                plt.ylabel('Time Error (ms)')
                plt.title('Sync Time Errors')
                plt.grid(True, alpha=0.3)
                
                buf_sync = io.BytesIO()
                plt.savefig(buf_sync, format='png', dpi=150, bbox_inches='tight')
                buf_sync.seek(0)
                img_sync_base64 = base64.b64encode(buf_sync.read()).decode()
                self.visualizations['sync_errors'] = img_sync_base64
                plt.close()
            
            self.logger.log_info("可视化图表生成完成")
            
        except Exception as e:
            self.logger.log_error(f"可视化生成失败: {str(e)}")
            # 继续处理，不中断流程
    
    def _prepare_export_data(self):
        """准备导出数据，兼容MAT和NWB格式"""
        try:
            exp_day, exp_subject = self.data_loader.metadata['monkeylogic']['file_path'].name.split('_')[1:3]
            # 基础元数据
            self.export_data = {
                'session_info': {
                    'data_path': str(self.data_path),
                    'exp_day': exp_day,
                    'exp_subject': exp_subject,
                    'dataset_path': str(self.dataset_path),
                    'dataset_name': self.dataset_name,
                    'processing_timestamp': pd.Timestamp.now().isoformat(),
                    'imgset_size': self.imgset_size,
                    'valid_eye_count': self.valid_eye_count
                },
                
                # 同步信息
                'sync_info': {
                    'sync_line': self.sync_line,
                    'stim_start_times': self.onset_time_ms.tolist() if self.onset_time_ms is not None else [],
                    'stim_end_times': self.stim_end_times.tolist() if self.stim_end_times is not None else [],
                },
                
                # 试次验证结果
                'trial_validation': {
                    'trial_valid_idx': self.trial_valid_idx.tolist() if self.trial_valid_idx is not None else [],
                    'dataset_valid_idx': self.dataset_valid_idx.tolist() if self.dataset_valid_idx is not None else [],
                    'eye_threshold': self.params['eye_threshold'],
                    'valid_trial_count': self.valid_eye_count
                },
                
                # 眼动数据
                'eye_data': {
                    'eye_matrix': self.eye_matrix.tolist() if self.eye_matrix is not None else [],
                    'eye_matrix_shape': self.eye_matrix.shape if self.eye_matrix is not None else [0, 0, 0]
                },
                
                # 原始数据引用
                'data_references': {
                    'behavior_data': {
                        'file_path': str(self.data_loader.metadata['monkeylogic']['file_path'])
                        }, 
                    'neural_metadata': {
                        'sampling_frequency': self.neural_data.get_sampling_frequency() if self.neural_data else 30000,
                        'num_channels': self.neural_data.get_num_channels() if self.neural_data else 0,
                        'duration': self.neural_data.get_total_duration() if self.neural_data else 0
                    }
                },
                
                # 处理参数
                'processing_params': self.params.copy()
            }
            
            self.logger.log_info("导出数据准备完成")
            
        except Exception as e:
            self.logger.log_error(f"导出数据准备失败: {str(e)}")
            raise
    
    def _save_dict_to_hdf5(self, data_dict, filename):
        """将复杂Python字典保存为HDF5格式"""
        import h5py
        with h5py.File(filename, 'w') as f:
            def save_recursive(group, data):
                for key, value in data.items():
                    if isinstance(value, dict):
                        # 创建子组处理嵌套字典
                        subgroup = group.create_group(key)
                        save_recursive(subgroup, value)
                    elif isinstance(value, np.ndarray):
                        # 直接保存NumPy数组
                        group.create_dataset(key, data=value, compression='gzip')
                    elif isinstance(value, (list, tuple)):
                        # 处理列表和元组
                        if all(isinstance(item, str) for item in value):
                            # 字符串列表特殊处理
                            string_dt = h5py.special_dtype(vlen=str)
                            group.create_dataset(key, data=value, dtype=string_dt)
                        else:
                            # 尝试转换为数组
                            try:
                                group.create_dataset(key, data=np.array(value))
                            except:
                                # 如果无法转换，保存为字符串
                                group.create_dataset(key, data=str(value))
                    else:
                        # 基本数据类型作为属性保存
                        group.attrs[key] = value
            
            save_recursive(f, data_dict)
        
            # 添加全局元数据
            f.attrs['format_version'] = '1.0'
            f.attrs['created_with'] = 'Python h5py'
            f.attrs['numpy_version'] = np.__version__

    def check_hdf5_compatibility(self, data_dict, path=""):
        """
        检查复杂字典中哪些键值对不能被写入HDF5格式
        
        Args:
            data_dict: 要检查的字典
            path: 当前路径（用于递归）
        
        Returns:
            Dict[str, List]: 包含不兼容项的详细报告
        """
        import h5py
        
        def is_hdf5_compatible_scalar(value):
            """检查值是否可以作为HDF5属性保存"""
            if isinstance(value, (str, int, float, bool, np.integer, np.floating)):
                return True
            if isinstance(value, np.ndarray) and value.ndim == 0:  # scalar array
                return value.dtype != np.dtype('O')
            return False
        
        def is_hdf5_compatible_dataset(value):
            """检查值是否可以作为HDF5数据集保存"""
            if isinstance(value, np.ndarray):
                # 检查数组类型
                if value.dtype == np.dtype('O'):
                    return False, f"Object dtype array: {value.dtype}"
                if np.issubdtype(value.dtype, np.complexfloating):
                    return False, f"Complex dtype not supported: {value.dtype}"
                return True, "Compatible array"
            elif isinstance(value, (list, tuple)):
                try:
                    arr = np.array(value)
                    if arr.dtype == np.dtype('O'):
                        return False, f"List/tuple contains objects: {type(value[0]) if value else 'empty'}"
                    return True, "Compatible list/tuple"
                except Exception as e:
                    return False, f"Cannot convert to array: {str(e)}"
            elif isinstance(value, (str, int, float, bool)):
                return True, "Compatible scalar"
            else:
                return False, f"Unsupported type: {type(value)}"
        
        # 结果存储
        compatibility_report = {
            'incompatible_attributes': [],  # 不能作为属性保存的项
            'incompatible_datasets': [],    # 不能作为数据集保存的项
            'problematic_objects': [],      # 包含问题对象的项
            'summary': {}
        }
        
        def check_recursive(data, current_path=""):
            """递归检查字典"""
            if not isinstance(data, dict):
                return
                
            for key, value in data.items():
                full_path = f"{current_path}/{key}" if current_path else key
                
                if isinstance(value, dict):
                    # 递归检查嵌套字典
                    check_recursive(value, full_path)
                else:
                    # 检查是否可以作为属性保存
                    attr_compatible = is_hdf5_compatible_scalar(value)
                    dataset_compatible, dataset_reason = is_hdf5_compatible_dataset(value)
                    
                    if not attr_compatible and not dataset_compatible:
                        # 完全不兼容
                        compatibility_report['incompatible_attributes'].append({
                            'path': full_path,
                            'type': str(type(value)),
                            'value_preview': str(value)[:100] + ('...' if len(str(value)) > 100 else ''),
                            'reason': f"Cannot save as attribute or dataset: {dataset_reason}"
                        })
                    elif not attr_compatible:
                        # 不能作为属性，但可能可以作为数据集
                        if isinstance(value, np.ndarray) and value.dtype == np.dtype('O'):
                            compatibility_report['problematic_objects'].append({
                                'path': full_path,
                                'type': 'numpy.ndarray with object dtype',
                                'shape': value.shape,
                                'sample_values': [str(item) for item in value.flat[:5]],
                                'suggestion': 'Convert to string array or save as pickle'
                            })
                        elif isinstance(value, (list, tuple)):
                            try:
                                arr = np.array(value)
                                if arr.dtype == np.dtype('O'):
                                    compatibility_report['problematic_objects'].append({
                                        'path': full_path,
                                        'type': f'{type(value).__name__} with mixed types',
                                        'length': len(value),
                                        'sample_types': [str(type(item)) for item in value[:5]],
                                        'suggestion': 'Convert all elements to same type or save as strings'
                                    })
                            except:
                                pass
    
        # 执行检查
        check_recursive(data_dict)
        
        # 生成摘要
        compatibility_report['summary'] = {
            'total_incompatible_attributes': len(compatibility_report['incompatible_attributes']),
            'total_incompatible_datasets': len(compatibility_report['incompatible_datasets']),
            'total_problematic_objects': len(compatibility_report['problematic_objects']),
            'needs_conversion': len(compatibility_report['problematic_objects']) > 0
        }
        
        return compatibility_report

    def print_compatibility_report(self, report):
        """打印兼容性检查报告"""
        print("=== HDF5 兼容性检查报告 ===\n")
        
        print(f"摘要:")
        print(f"  - 不兼容属性: {report['summary']['total_incompatible_attributes']}")
        print(f"  - 不兼容数据集: {report['summary']['total_incompatible_datasets']}")
        print(f"  - 问题对象: {report['summary']['total_problematic_objects']}")
        print(f"  - 需要转换: {'是' if report['summary']['needs_conversion'] else '否'}\n")
        
        if report['incompatible_attributes']:
            print("完全不兼容的项:")
            for item in report['incompatible_attributes']:
                print(f"  路径: {item['path']}")
                print(f"  类型: {item['type']}")
                print(f"  原因: {item['reason']}")
                print(f"  预览: {item['value_preview']}\n")
        
        if report['problematic_objects']:
            print("需要转换的对象:")
            for item in report['problematic_objects']:
                print(f"  路径: {item['path']}")
                print(f"  类型: {item['type']}")
                if 'shape' in item:
                    print(f"  形状: {item['shape']}")
                    print(f"  样本值: {item['sample_values']}")
                if 'length' in item:
                    print(f"  长度: {item['length']}")
                    print(f"  样本类型: {item['sample_types']}")
                print(f"  建议: {item['suggestion']}\n")

    def fix_incompatible_data(self, data_dict):
        """
        自动修复不兼容的数据
        
        Args:
            data_dict: 要修复的字典
        
        Returns:
            Dict: 修复后的字典
        """
        def fix_recursive(data):
            if isinstance(data, dict):
                fixed_dict = {}
                for key, value in data.items():
                    fixed_dict[key] = fix_recursive(value)
                return fixed_dict
            elif isinstance(value, np.ndarray):
                if value.dtype == np.dtype('O'):
                    # 对象数组转换为字符串数组
                    try:
                        return np.array([str(item) for item in value.flatten()]).reshape(value.shape)
                    except:
                        return str(value)
                elif np.issubdtype(value.dtype, np.complexfloating):
                    # 复数转换为实数（或分别保存实部和虚部）
                    return np.abs(value)  # 或者可以返回 {'real': value.real, 'imag': value.imag}
                return value
            elif isinstance(value, (list, tuple)):
                try:
                    arr = np.array(value)
                    if arr.dtype == np.dtype('O'):
                        # 混合类型列表转换为字符串列表
                        return [str(item) for item in value]
                    return arr
                except:
                    return [str(item) for item in value]
            else:
                return value
        
        return fix_recursive(data_dict)

    def _export_data_to_hdf5(self):
        """导出数据到MAT文件"""
        try:
            self._save_dict_to_hdf5(self.export_data, self.h5_file)
        except Exception as e:
            self.logger.log_error(f"导出数据到MAT文件失败: {str(e)}")
            raise
    
    # Streamlit界面通讯方法
    def get_processing_status(self) -> Dict[str, Any]:
        """获取处理状态供Streamlit显示"""
        return {
            'processing_complete': self.processing_complete,
            'onset_times_ml': self.onset_times_ml,
            'onset_times_sglx': self.onset_times_sglx,
            'valid_eye_count': self.valid_eye_count,
            'dataset_name': self.dataset_name,
            'imgset_size': self.imgset_size,
            'sync_status': self.sync_line['status'] if self.sync_line else 'unknown'
        }
    
    def get_visualizations(self) -> Dict[str, str]:
        """获取可视化图表的base64编码"""
        return self.visualizations.copy()
    
    def get_export_data(self) -> Dict[str, Any]:
        """获取导出数据"""
        return self.export_data.copy()
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """获取处理摘要统计"""
        stats = {
            'total_trials': self.behavior_data.get('num_trials', 0) if self.behavior_data else 0,
            'total_onsets_ml': self.onset_times_ml,
            'total_onsets_sglx': self.onset_times_sglx,
            'valid_eye_trials': self.valid_eye_count,
            'unique_stimuli': self.imgset_size,
            'dataset_name': self.dataset_name
        }
        
        if self.sync_line and self.sync_line['status'] == 'success':
            stats.update({
                'sync_events': self.sync_line['ni_events'],
                'sync_mean_error_ms': self.sync_line['mean_error']
            })
        
        return stats
    
    # 兼容性方法（保持与原接口一致）
    def align_timestamps(self) -> bool:
        """兼容性方法：对齐时间戳"""
        return self.process_full_synchronization()
    
    def calibrate_onsets(self) -> bool:
        """兼容性方法：校准onset"""
        return True  # 已在process_full_synchronization中完成
    
    def validate_trials(self) -> bool:
        """兼容性方法：验证试次"""
        return True  # 已在process_full_synchronization中完成
    
    def get_sync_result(self) -> Optional[Dict]:
        """兼容性方法：获取同步结果"""
        return self.export_data if self.processing_complete else None
    
    def export_sync_info(self, output_path: str):
        """导出同步信息到文件"""
        if not self.processing_complete:
            raise ProcessingError("处理未完成，无法导出")
        
        try:
            import json
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.export_data, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.log_info(f"同步信息已导出到: {output_file}")
            
        except Exception as e:
            raise ProcessingError(f"导出同步信息失败: {str(e)}")


def shaded_error_bar(data, before_onset_measure=0, color='blue', alpha=0.3, 
                     xlabel='Time from event', title='Signal'):
    """
    绘制带阴影误差条的图形，用于光敏二极管信号可视化
    """
    x = np.arange(data.shape[1]) - before_onset_measure
    mean_line = np.mean(data, axis=0)
    std_line = np.std(data, axis=0)
    
    plt.plot(x, mean_line, color=color, linewidth=2, label='Mean')
    plt.fill_between(x, 
                     mean_line - std_line, 
                     mean_line + std_line, 
                     alpha=alpha, 
                     color=color,
                     label='±1 STD')
    
    plt.xlabel(xlabel)
    plt.title(title)
    plt.legend()
    plt.grid(True, alpha=0.3)
