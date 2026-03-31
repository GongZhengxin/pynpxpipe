"""
数据加载与验证模块

负责加载SpikeGLX和MonkeyLogic数据，并进行数据验证
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import warnings
import os

# 数据处理相关导入
try:
    import spikeinterface.full as si
    SPIKEINTERFACE_AVAILABLE = True
except ImportError:
    SPIKEINTERFACE_AVAILABLE = False
    warnings.warn("SpikeInterface not available. Some functionality will be limited.")

try:
    import scipy.io as sio
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    warnings.warn("SciPy not available. MAT file support will be limited.")

try:
    import mat73
    MAT73_AVAILABLE = True
except ImportError:
    MAT73_AVAILABLE = False
    warnings.warn("mat73 not available. v7.3 MAT file support will be limited.")

try:
    import matlab.engine
    MATLAB_AVAILABLE = True
except ImportError:
    MATLAB_AVAILABLE = False
    warnings.warn("MATLAB Engine not available. BHV2 file support will be limited.")

from utils.logger import ProcessLogger
from utils.error_handler import DataLoadError, ValidationError, error_boundary
from utils.config_manager import get_config_manager


class DataLoader:
    """
    数据加载器类
    
    用于加载和验证SpikeGLX神经数据和MonkeyLogic行为数据
    """
    
    def __init__(self, data_path: str, matlab_util_path: Optional[str] = None):
        """
        初始化数据加载器
        
        Args:
            data_path: 数据目录路径
            matlab_util_path: MATLAB工具函数路径（包含mlread等函数）
        """
        self.data_path = Path(data_path)
        if not os.path.exists(self.data_path):
            raise DataLoadError(f"数据目录不存在: {self.data_path}")
        
        self.matlab_util_path = matlab_util_path or str(Path(__file__).parent.parent / 'Util')
        self.logger = ProcessLogger()
        
        # 获取配置管理器和配置
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_data_loader_config()
        
        # 从配置获取参数
        self.spikeglx_config = self.config.get('spikeglx', {})
        self.monkeylogic_config = self.config.get('monkeylogic', {})
        self.validation_config = self.config.get('validation', {})
        
        # 数据存储
        self.spikeglx_data = None
        self.monkeylogic_data = None
        self.metadata = {}
        
        # 同步相关数据
        self.sync_data = {
            'nidq_analog': None,
            'nidq_digital': None, 
            'nidq_meta': None,
            'imec_sync': None,
            'imec_meta': None
        }
        
        # 验证状态
        self.is_validated = False
        self.validation_results = {}
        
        # 初始化MATLAB引擎（如果可用）
        self.matlab_engine = None
        if MATLAB_AVAILABLE and self.matlab_util_path:
            self._init_matlab_engine()
        
        # 处理元数据
        from datetime import datetime
        self.metadata['process_info'] = {
            'data_path': self.data_path,
            'process_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def _init_matlab_engine(self):
        """初始化MATLAB引擎"""
        try:
            self.matlab_engine = matlab.engine.start_matlab()
            if self.matlab_util_path:
                self.matlab_engine.addpath(self.matlab_util_path, nargout=0)
            self.logger.log_info("MATLAB引擎初始化成功")
        except Exception as e:
            self.logger.log_warning(f"MATLAB引擎初始化失败: {str(e)}")
            self.matlab_engine = None

    @error_boundary("SpikeGLX数据加载")
    def load_spikeglx(self, stream_name: Optional[str] = None) -> bool:
        """
        加载SpikeGLX数据，包括同步信号
        
        Args:
            stream_name: 数据流名称，如果为None则从配置获取
            
        Returns:
            是否成功加载
        """
        if not SPIKEINTERFACE_AVAILABLE:
            raise DataLoadError("SpikeInterface未安装，无法加载SpikeGLX数据")
        
        # 从配置获取默认流名称
        if stream_name is None:
            stream_name = self.spikeglx_config.get('stream_name', 'imec0.ap')
        
        step_idx = self.logger.start_step("load_spikeglx", f"加载SpikeGLX神经数据和同步信号 (流: {stream_name})")
        
        try:
            # 查找SpikeGLX文件夹
            spikeglx_folder = self._find_spikeglx_folder()
            if not spikeglx_folder:
                raise DataLoadError("未找到SpikeGLX数据文件夹")
            
            self.logger.log_info(f"找到SpikeGLX文件夹: {spikeglx_folder}")
            
            # 加载主数据流
            recording = si.read_spikeglx(spikeglx_folder, stream_name=stream_name)
            self.spikeglx_data = recording
            
            # 加载nidq同步数据
            self._load_nidq_sync_data(spikeglx_folder)
            
            # 加载imec同步数据
            self._load_imec_sync_data(spikeglx_folder)
            
            # 提取元数据
            self._extract_spikeglx_metadata(spikeglx_folder)
            
            self.logger.complete_step(step_idx, True, f"成功加载SpikeGLX数据和同步信号")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise DataLoadError(f"SpikeGLX数据加载失败: {str(e)}")
    
    def _find_spikeglx_folder(self) -> Optional[Path]:
        """查找SpikeGLX文件夹"""
        # 查找以NPX开头的文件夹
        npx_folders = list(self.data_path.glob("NPX*"))
        if npx_folders:
            return npx_folders[0]
        
        # 查找包含.bin和.meta文件的文件夹
        for folder in self.data_path.iterdir():
            if folder.is_dir():
                bin_files = list(folder.glob("*.bin"))
                meta_files = list(folder.glob("*.meta"))
                if bin_files and meta_files:
                    return folder
        
        return None
    
    def _load_nidq_sync_data(self, spikeglx_folder: Path):
        """加载nidq同步数据"""
        try:
            # 加载nidq记录
            nidq_rec = si.read_spikeglx(spikeglx_folder, stream_name='nidq')
            
            # 从配置获取数字通道映射
            digital_channel_map = self.spikeglx_config.get('digital_channel_map', {})
            
            # 获取模拟信号（光敏二极管）
            analog_trace = nidq_rec.get_traces(channel_ids=['nidq#XA0'])
            self.sync_data['nidq_analog'] = analog_trace
            
            # 获取数字信号
            digital_trace = nidq_rec.get_traces(channel_ids=['nidq#XD0'])
            self.sync_data['nidq_digital'] = digital_trace
            
            # 获取元数据
            nidq_meta = nidq_rec.neo_reader.signals_info_dict[(0, 'nidq')]['meta']
            self.sync_data['nidq_meta'] = nidq_meta
            
            # 存储数字通道映射到同步数据中
            self.sync_data['digital_channel_map'] = digital_channel_map
            
            self.logger.log_info("成功加载nidq同步数据")
            if digital_channel_map:
                self.logger.log_info(f"数字通道映射: {digital_channel_map}")
            
        except Exception as e:
            self.logger.log_warning(f"加载nidq同步数据失败: {str(e)}")
    
    def _load_imec_sync_data(self, spikeglx_folder: Path):
        """加载imec同步数字信号数据"""
        try:
            # 加载imec0.lf-SYNC记录
            imec_rec = si.read_spikeglx(spikeglx_folder, stream_name='imec0.lf-SYNC')
            
            # 获取同步信号
            sync_trace = imec_rec.get_traces(channel_ids=['imec0.lf#SY0'])
            self.sync_data['imec_sync'] = sync_trace
            
            # 获取元数据
            imec_meta = imec_rec.neo_reader.signals_info_dict[(0, 'imec0.lf')]['meta']
            self.sync_data['imec_meta'] = imec_meta
            
            self.logger.log_info("成功加载imec同步数据")
            
        except Exception as e:
            self.logger.log_warning(f"加载imec同步数据失败: {str(e)}")
    
    def _extract_spikeglx_metadata(self, folder_path: Path):
        """提取SpikeGLX元数据"""
        if self.spikeglx_data:
            self.metadata['spikeglx'] = {
                'folder_path': folder_path,
                'sampling_frequency': self.spikeglx_data.get_sampling_frequency(),
                'num_channels': self.spikeglx_data.get_num_channels(),
                'num_frames': self.spikeglx_data.get_num_frames(),
                'duration': self.spikeglx_data.get_total_duration(),
                'probe_info': self.spikeglx_data.get_annotation('probes_info')
            }
    
    @error_boundary("MonkeyLogic数据加载")
    def load_monkeylogic(self) -> bool:
        """
        加载MonkeyLogic行为数据
        使用MATLAB引擎读取.bhv2文件，转换为.mat后用scipy.io或mat73加载
        
        Returns:
            是否成功加载
        """
        step_idx = self.logger.start_step("load_monkeylogic", "加载MonkeyLogic行为数据")
        
        try:
            # 从配置获取文件扩展名
            file_extension = self.monkeylogic_config.get('file_extension', '.bhv2')
            
            # 查找bhv2文件
            pattern = f"*{file_extension}"
            bhv2_files = list(self.data_path.glob(pattern))
            if not bhv2_files:
                bhv2_files = list(self.data_path.glob(f"**/{pattern}"))
            
            if not bhv2_files:
                raise DataLoadError(f"未找到MonkeyLogic {file_extension}文件")
            
            # 使用第一个找到的bhv2文件
            bhv2_file = bhv2_files[0]
            self.logger.log_info(f"找到MonkeyLogic文件: {bhv2_file}")
            
            # 检查是否已有.mat文件
            processed_dir = self.data_path / "processed"
            processed_dir.mkdir(exist_ok=True)
            mat_file = processed_dir / f"ML_{bhv2_file.stem}.mat"
            self.mat_file_path = mat_file

            if not mat_file.exists() and self.matlab_engine:
                # 使用MATLAB引擎转换bhv2到mat
                self._convert_bhv2_to_mat(bhv2_file, mat_file)
            
            # 加载.mat文件
            if mat_file.exists():
                self.monkeylogic_data = self._load_mat_file(mat_file)
            else:
                # 回退到模拟数据
                self.logger.log_warning("无法载入bhv2文件，使用模拟数据")
                self.monkeylogic_data = self._create_mock_monkeylogic_data(bhv2_file)

            # 提取元数据
            self._extract_monkeylogic_metadata()
            
            self.logger.complete_step(step_idx, True, f"成功加载MonkeyLogic数据")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise DataLoadError(f"MonkeyLogic数据加载失败: {str(e)}")
    
    def _convert_bhv2_to_mat(self, bhv2_file: Path, mat_file: Path):
        """使用MATLAB引擎将bhv2转换为mat文件"""
        try:
            self.logger.log_info(f"转换{bhv2_file.name}到{mat_file.name}")
            
            # 切换到数据目录
            self.matlab_engine.cd(str(self.data_path), nargout=0)
            
            # 调用mlread函数
            self.matlab_engine.eval(f"trial_ML = mlread('{str(bhv2_file.name)}');", nargout=0)
            
            # 保存为mat文件
            self.matlab_engine.eval(f"save('{str(mat_file)}', 'trial_ML', '-v7');", nargout=0)
            
            self.logger.log_info(f"成功转换bhv2文件到{mat_file}")
            
        except Exception as e:
            self.logger.log_warning(f"bhv2转换失败: {str(e)}")
            raise
    
    def _load_mat_file(self, mat_file: Path) -> Dict[str, Any]:
        """加载.mat文件"""
        if not SCIPY_AVAILABLE:
            raise DataLoadError("SciPy未安装，无法加载MAT文件")
            
        try:
            # 优先使用scipy.io加载标准MATLAB格式（-v7）
            mat_data = sio.loadmat(str(mat_file), squeeze_me=True)
            self.logger.log_info("使用scipy.io成功加载MAT文件")
            return self._parse_scipy_mat(mat_data)
        except Exception as e1:
            self.logger.log_warning(f"scipy.io加载失败: {str(e1)}")
            
            if MAT73_AVAILABLE:
                try:
                    # 回退到mat73加载v7.3格式
                    mat_data = mat73.loadmat(str(mat_file))
                    self.logger.log_info("使用mat73成功加载MAT文件")
                    return self._parse_mat73_data(mat_data)
                except Exception as e2:
                    self.logger.log_error(f"mat73加载也失败: {str(e2)}")
                    raise DataLoadError(f"无法加载MAT文件: scipy={str(e1)}, mat73={str(e2)}")
            else:
                self.logger.log_error("mat73未安装，无法尝试v7.3格式")
                raise DataLoadError(f"无法加载MAT文件: {str(e1)}")
    
    def _parse_mat73_data(self, mat_data: Dict) -> Dict[str, Any]:
        """解析mat73加载的.mat文件 HOPE NEVER USE IT"""
        # mat73直接返回字典，类似scipy但支持v7.3格式
        trial_ml = mat_data.get('trial_ML', None)
        if trial_ml is not None:
            return self._parse_trial_ml_data(trial_ml)
        else:
            return {k: v for k, v in mat_data.items() if not k.startswith('__')}
    
    def _parse_scipy_mat(self, mat_data: Dict) -> Dict[str, Any]:
        """解析scipy加载的.mat文件"""
        # 移除MATLAB特有的变量
        trial_ml = mat_data.get('trial_ML', None)
        if trial_ml is not None:
            return self._parse_trial_ml_data(trial_ml)
        else:
            self.logger.log_warning(f"未找到trial_ML数据: {mat_data.keys()}")
            return {k: v for k, v in mat_data.items() if not k.startswith('__')}
    
    def _parse_trial_ml_data(self, trial_ml) -> Dict[str, Any]:
        """解析trial_ML数据结构，按字段组织数据而非按试次"""
        parsed_data = {
            'num_trials': 0,
            'duration': 0,
            'file_path': self.mat_file_path,
            'Trial': [],
            'BehavioralCodes': {},
            'AnalogData': {},
            'UserVars': {},
            'VariableChanges': {},
        }
        
        try:
            # 处理不同类型的trial_ml数据
            if isinstance(trial_ml, np.ndarray):
                trials_objarray = trial_ml
            else:
                self.logger.log_warning(f"未知的trial_ML数据类型: {type(trial_ml)}")
                return parsed_data
            
            parsed_data['num_trials'] = len(trials_objarray)
            self.logger.log_info(f"解析{len(trials_objarray)}个试次的MonkeyLogic数据")
            
            # 检查数据结构
            if len(trials_objarray) > 0:
                field_names = trials_objarray.dtype.names
                self.logger.log_info(f"可用字段: {field_names}")
                
                # 解析Trial字段
                if 'Trial' in field_names:
                    parsed_data['Trial'] = [int(trial) for trial in trials_objarray['Trial']]
                
                # 解析BehavioralCodes字段
                if 'BehavioralCodes' in field_names:
                    parsed_data['BehavioralCodes'] = self._extract_behavioral_codes_all_trials(trials_objarray)
                
                # 解析AnalogData字段
                if 'AnalogData' in field_names:
                    parsed_data['AnalogData'] = self._extract_analog_data_all_trials(trials_objarray)
                
                # 解析UserVars字段
                if 'UserVars' in field_names:
                    parsed_data['UserVars'] = self._extract_user_vars_all_trials(trials_objarray)
                
                # 解析VariableChanges字段
                if 'VariableChanges' in field_names:
                    parsed_data['VariableChanges'] = self._extract_variable_changes_all_trials(trials_objarray)
            
                parsed_data['duration'] = (trials_objarray['AbsoluteTrialStartTime'][-1] \
                                        + parsed_data['BehavioralCodes']['CodeTimes'][-1][-1]) / 1000 
            
            self.logger.log_info("MonkeyLogic数据解析完成")
        
        except Exception as e:
            self.logger.log_warning(f"解析trial_ML数据失败: {str(e)}")
            
        return parsed_data
    
    def _extract_behavioral_codes_all_trials(self, trials_objarray) -> Dict[str, Any]:
        """提取所有试次的行为代码，按字段组织"""
        behavioral_codes = {
            'CodeTimes': [],
            'CodeNumbers': []
        }
        
        try:
            # 检查BehavioralCodes字段的子字段
            if len(trials_objarray) > 0:
                first_bc = trials_objarray['BehavioralCodes'][0]
                if hasattr(first_bc, 'dtype') and first_bc.dtype.names:
                    bc_fields = first_bc.dtype.names
                    self.logger.log_info(f"BehavioralCodes子字段: {bc_fields}")
                
                # 遍历每个试次，提取行为代码
                for i, trial_bc in enumerate(trials_objarray['BehavioralCodes']):
                    try:
                        if hasattr(trial_bc, 'dtype') and trial_bc.dtype.names:
                            # 使用结构化数组访问
                            if 'CodeTimes' in trial_bc.dtype.names:
                                code_times = trial_bc['CodeTimes'].flatten() if trial_bc['CodeTimes'].size > 0 else np.array([])
                                behavioral_codes['CodeTimes'].append(code_times.item())
                            else:
                                behavioral_codes['CodeTimes'].append([])
                                
                            if 'CodeNumbers' in trial_bc.dtype.names:
                                code_numbers = trial_bc['CodeNumbers'].flatten() if trial_bc['CodeNumbers'].size > 0 else np.array([])
                                behavioral_codes['CodeNumbers'].append(code_numbers.item())
                            else:
                                behavioral_codes['CodeNumbers'].append([])
                        else:
                            # 如果不是结构化数组，尝试直接访问属性
                            if hasattr(trial_bc, 'CodeTimes'):
                                code_times = np.array(trial_bc.CodeTimes).flatten()
                                behavioral_codes['CodeTimes'].append(code_times.item())
                            else:
                                behavioral_codes['CodeTimes'].append([])
                                
                            if hasattr(trial_bc, 'CodeNumbers'):
                                code_numbers = np.array(trial_bc.CodeNumbers).flatten()
                                behavioral_codes['CodeNumbers'].append(code_numbers.item())
                            else:
                                behavioral_codes['CodeNumbers'].append([])
                                
                    except Exception as e:
                        self.logger.log_warning(f"提取试次{i}行为代码失败: {str(e)}")
                        behavioral_codes['CodeTimes'].append([])
                        behavioral_codes['CodeNumbers'].append([])
                        
        except Exception as e:
            self.logger.log_warning(f"提取行为代码失败: {str(e)}")
            
        return behavioral_codes
    
    def  _extract_analog_data_all_trials(self, trials_objarray) -> Dict[str, Any]:
        """提取所有试次的模拟数据，按字段组织"""
        analog_data = {
            'Eye': [],
            'SampleInterval': []
        }
        
        try:
            # 遍历每个试次，提取模拟数据
            for i, trial_ad in enumerate(trials_objarray['AnalogData']):
                try:
                    if hasattr(trial_ad, 'dtype') and trial_ad.dtype.names:
                        # 使用结构化数组访问
                        if 'Eye' in trial_ad.dtype.names:
                            eye_data = trial_ad['Eye']
                            if eye_data.size > 0:
                                analog_data['Eye'].append(eye_data.item())
                            else:
                                analog_data['Eye'].append(None)
                        else:
                            analog_data['Eye'].append(None)
                            
                        if 'SampleInterval' in trial_ad.dtype.names:
                            sample_interval = float(trial_ad['SampleInterval'].item())
                            analog_data['SampleInterval'].append(sample_interval)
                        else:
                            analog_data['SampleInterval'].append(None)
                    else:
                        # 尝试直接访问属性
                        if hasattr(trial_ad, 'Eye'):
                            analog_data['Eye'].append(np.array(trial_ad.Eye.item()))
                        else:
                            analog_data['Eye'].append(None)
                            
                        if hasattr(trial_ad, 'SampleInterval'):
                            analog_data['SampleInterval'].append(float(trial_ad.SampleInterval.item()))
                        else:
                            analog_data['SampleInterval'].append(None)
                            
                except Exception as e:
                    self.logger.log_warning(f"提取试次{i}模拟数据失败: {str(e)}")
                    analog_data['Eye'].append(None)
                    analog_data['SampleInterval'].append(1.0)
                    
        except Exception as e:
            self.logger.log_warning(f"提取模拟数据失败: {str(e)}")
            
        return analog_data
    
    def _extract_user_vars_all_trials(self, trials_objarray) -> Dict[str, Any]:
        """提取所有试次的用户变量，按字段组织"""
        user_vars = {}
        
        try:
            # 先检查第一个试次的UserVars结构
            if len(trials_objarray) > 0:
                first_uv = trials_objarray['UserVars'][0]
                if hasattr(first_uv, 'dtype') and first_uv.dtype.names:
                    uv_fields = first_uv.dtype.names
                    self.logger.log_info(f"UserVars字段: {uv_fields}")
                    
                    # 为每个字段初始化列表
                    for field in uv_fields:
                        user_vars[field] = []
                
                # 遍历每个试次，提取用户变量
                for i, trial_uv in enumerate(trials_objarray['UserVars']):
                    try:
                        if hasattr(trial_uv, 'dtype') and trial_uv.dtype.names:
                            for field in trial_uv.dtype.names:
                                if field not in user_vars:
                                    user_vars[field] = []
                                value = trial_uv[field]
                                # 处理不同类型的值
                                if hasattr(value, 'size') and value.size == 1:
                                    user_vars[field].append(value.item())
                                elif hasattr(value, 'tolist'):
                                    user_vars[field].append(value.tolist())
                                else:
                                    user_vars[field].append(value)
                        else:
                            # 如果结构不明确，跳过该试次
                            for field in user_vars:
                                user_vars[field].append(None)
                                
                    except Exception as e:
                        self.logger.log_warning(f"提取试次{i}用户变量失败: {str(e)}")
                        for field in user_vars:
                            user_vars[field].append(None)
                            
        except Exception as e:
            self.logger.log_warning(f"提取用户变量失败: {str(e)}")
            
        return user_vars
    
    def _extract_variable_changes_all_trials(self, trials_objarray) -> Dict[str, Any]:
        """提取所有试次的变量变化，按字段组织"""
        variable_changes = {}
        
        try:
            # 先检查第一个试次的VariableChanges结构
            if len(trials_objarray) > 0:
                first_vc = trials_objarray['VariableChanges'][0]
                if hasattr(first_vc, 'dtype') and first_vc.dtype.names:
                    vc_fields = first_vc.dtype.names
                    self.logger.log_info(f"VariableChanges字段: {vc_fields}")
                    
                    # 为每个字段初始化列表
                    for field in vc_fields:
                        variable_changes[field] = []
                
                # 遍历每个试次，提取变量变化
                for i, trial_vc in enumerate(trials_objarray['VariableChanges']):
                    try:
                        if hasattr(trial_vc, 'dtype') and trial_vc.dtype.names:
                            for field in trial_vc.dtype.names:
                                if field not in variable_changes:
                                    variable_changes[field] = []
                                value = trial_vc[field]
                                # 处理不同类型的值
                                if hasattr(value, 'size') and value.size == 1:
                                    variable_changes[field].append(value.item())
                                elif hasattr(value, 'tolist'):
                                    variable_changes[field].append(value.tolist())
                                else:
                                    variable_changes[field].append(value)
                        else:
                            # 如果结构不明确，跳过该试次
                            for field in variable_changes:
                                variable_changes[field].append(None)
                                
                    except Exception as e:
                        self.logger.log_warning(f"提取试次{i}变量变化失败: {str(e)}")
                        for field in variable_changes:
                            variable_changes[field].append(None)
                            
        except Exception as e:
            self.logger.log_warning(f"提取变量变化失败: {str(e)}")
            
        return variable_changes

    def _extract_monkeylogic_metadata(self):
        """提取MonkeyLogic元数据"""
        if self.monkeylogic_data:
            self.metadata['monkeylogic'] = {
                'num_trials': self.monkeylogic_data.get('num_trials'),
                'file_path': self.monkeylogic_data.get('file_path'),
            }
    
    @error_boundary("数据验证")
    def validate_data(self) -> bool:
        """
        验证加载的数据
        
        Returns:
            验证是否通过
        """
        step_idx = self.logger.start_step("validate_data", "验证数据完整性和一致性")
        
        validation_results = {
            'spikeglx_valid': False,
            'monkeylogic_valid': False,
            'temporal_alignment': False,
            'issues': []
        }
        
        try:
            # 验证SpikeGLX数据
            if self.spikeglx_data:
                validation_results['spikeglx_valid'] = self._validate_spikeglx_data()
            else:
                validation_results['issues'].append("SpikeGLX数据未加载")
            
            # 验证MonkeyLogic数据
            if self.monkeylogic_data:
                validation_results['monkeylogic_valid'] = self._validate_monkeylogic_data()
            else:
                validation_results['issues'].append("MonkeyLogic数据未加载")
            
            # 验证时间对齐
            if self.spikeglx_data and self.monkeylogic_data:
                validation_results['temporal_alignment'] = self._validate_temporal_alignment()
            else:
                validation_results['issues'].append("无法验证时间对齐：缺少数据")
            
            self.validation_results = validation_results
            
            # 判断整体验证结果
            overall_valid = (
                validation_results['spikeglx_valid'] and
                validation_results['monkeylogic_valid'] and
                validation_results['temporal_alignment']
            )
            
            self.is_validated = overall_valid
            
            if overall_valid:
                self.logger.complete_step(step_idx, True, "数据验证通过")
            else:
                issues_str = "; ".join(validation_results['issues'])
                self.logger.complete_step(step_idx, False, f"数据验证失败: {issues_str}")
            
            return overall_valid
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise ValidationError(f"数据验证过程出错: {str(e)}")
    
    def _validate_spikeglx_data(self) -> bool:
        """验证SpikeGLX数据"""
        issues = []
        
        # 检查基本属性
        if not self.metadata['spikeglx'].get('sampling_frequency'):
            issues.append("缺少采样频率信息")
        
        if not self.metadata['spikeglx'].get('num_channels'):
            issues.append("缺少通道数信息")
        
        if not self.metadata['spikeglx'].get('duration'):
            issues.append("缺少录制时长信息")
        
        # 检查采样频率是否合理（通常在20-50kHz范围）
        fs = self.metadata['spikeglx'].get('sampling_frequency', 0)
        if fs < 10000 or fs > 100000:
            issues.append(f"采样频率异常: {fs} Hz")
        
        # 检查通道数是否合理
        n_channels = self.metadata['spikeglx'].get('num_channels', 0)
        if n_channels < 1 or n_channels > 1025:
            issues.append(f"通道数异常: {n_channels}")
        
        if issues:
            self.validation_results.setdefault('issues', []).extend(issues)
            return False
        
        return True
    
    def _validate_monkeylogic_data(self) -> bool:
        """验证MonkeyLogic数据"""
        issues = []
        
        # 检查试次数量
        num_trials = self.monkeylogic_data.get('num_trials', 0)
        if num_trials < 1:
            issues.append("无有效试次数据")
        elif num_trials < 50:
            issues.append(f"试次数量较少: {num_trials}")
        
        # 检查行为代码
        behavioral_codes = self.monkeylogic_data.get('BehavioralCodes', {})
        
        # 从配置获取必需字段
        required_fields = self.monkeylogic_config.get('required_fields', ['BehavioralCodes', 'VariableChanges', 'AnalogData', 'UserVars'])
        
        # 检查基本字段是否存在
        missing_fields = []
        for field in required_fields:
            if field not in self.monkeylogic_data:
                missing_fields.append(field)
        
        if missing_fields:
            issues.append(f"缺少必要的数据字段: {missing_fields}")
        
        # 检查行为代码结构
        if 'BehavioralCodes' in self.monkeylogic_data:
            required_codes = ['CodeTimes', 'CodeNumbers']
            missing_codes = [code for code in required_codes if code not in behavioral_codes]
            if missing_codes:
                issues.append(f"缺少必要的行为代码: {missing_codes}")
        
        # 从配置获取代码映射并验证
        code_mappings = self.monkeylogic_config.get('code_mappings', {})
        if code_mappings:
            self.logger.log_info(f"行为代码映射: {code_mappings}")
        if issues:
            self.validation_results.setdefault('issues', []).extend(issues)
            return False
        
        return True
    
    def _validate_temporal_alignment(self) -> bool:
        """验证时间对齐"""
        issues = []
        
        # 检查时间范围是否重叠
        neural_duration = self.metadata['spikeglx'].get('duration', 0)
        
        trial_duration = self.monkeylogic_data.get('duration', 0)
        
        # 检查时间范围是否合理
        if (neural_duration - trial_duration) < 0:  # 5分钟容差
            issues.append(f"神经数据时长({neural_duration:.1f}s) 无法容纳 行为数据时长({trial_duration:.1f}s)")
        
        if issues:
            self.validation_results.setdefault('issues', []).extend(issues)
            return False
        
        return True
    
    def get_data_summary(self) -> Dict[str, Any]:
        """获取数据摘要信息"""
        summary = {
            'data_path': str(self.data_path),
            'is_validated': self.is_validated,
            'metadata': self.metadata.copy()
        }
        
        if self.spikeglx_data:
            summary['spikeglx'] = {
                'loaded': True,
                'sampling_frequency': self.metadata['spikeglx'].get('sampling_frequency'),
                'num_channels': self.metadata['spikeglx'].get('num_channels'),
                'duration': self.metadata['spikeglx'].get('duration')
            }
        else:
            summary['spikeglx'] = {'loaded': False}
        
        if self.monkeylogic_data:
            summary['monkeylogic'] = {
                'loaded': True,
                'num_trials': self.monkeylogic_data.get('num_trials'),
                'file_path': self.monkeylogic_data.get('file_path')
            }
        else:
            summary['monkeylogic'] = {'loaded': False}
        
        if self.validation_results:
            summary['validation'] = self.validation_results.copy()
        
        return summary
    
    def get_spikeglx_data(self):
        """获取SpikeGLX数据"""
        return self.spikeglx_data
    
    def get_monkeylogic_data(self):
        """获取MonkeyLogic数据"""
        return self.monkeylogic_data
    
    def get_metadata(self) -> Dict[str, Any]:
        """获取元数据"""
        return self.metadata.copy()
    
    def get_sync_data(self) -> Dict[str, Any]:
        """获取同步数据"""
        return self.sync_data.copy()
    
    def close_matlab_engine(self):
        """关闭MATLAB引擎"""
        if self.matlab_engine:
            try:
                self.matlab_engine.quit()
                self.logger.log_info("MATLAB引擎已关闭")
            except Exception as e:
                self.logger.log_warning(f"关闭MATLAB引擎失败: {str(e)}")
            finally:
                self.matlab_engine = None
    
