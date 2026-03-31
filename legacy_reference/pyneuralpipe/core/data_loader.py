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
import pickle
import hashlib
import json

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
    import h5py
    H5PY_AVAILABLE = True
except ImportError:
    H5PY_AVAILABLE = False
    warnings.warn("h5py not available. v7.3 MAT file support will be limited.")

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
    def load_monkeylogic(self, use_cache: bool = True) -> bool:
        """
        加载MonkeyLogic行为数据
        使用MATLAB引擎读取.bhv2文件，转换为.mat后用h5py或scipy.io加载
        支持缓存机制，避免重复解析大文件
        
        Args:
            use_cache: 是否使用缓存，默认True
        
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
            
            # 缓存文件路径
            cache_file = processed_dir / f"ML_{bhv2_file.stem}_parsed.pkl"

            # 尝试从缓存加载
            if use_cache and cache_file.exists():
                cache_loaded = self._load_from_cache(cache_file, mat_file)
                if cache_loaded:
                    self._extract_monkeylogic_metadata()
                    self.logger.complete_step(step_idx, True, f"从缓存成功加载MonkeyLogic数据")
                    return True
                else:
                    self.logger.log_info("缓存无效，重新解析数据")

            # 如果没有mat文件，使用MATLAB引擎转换
            if not mat_file.exists() and self.matlab_engine:
                self._convert_bhv2_to_mat(bhv2_file, mat_file)
            
            # 加载.mat文件
            if mat_file.exists():
                self.monkeylogic_data = self._load_mat_file(mat_file)
                
                # 保存到缓存
                if use_cache and self.monkeylogic_data:
                    self._save_to_cache(cache_file, mat_file)
            else:
                # 回退到模拟数据
                self.logger.log_warning("无法载入bhv2文件，使用模拟数据")

            # 提取元数据
            self._extract_monkeylogic_metadata()
            
            self.logger.complete_step(step_idx, True, f"成功加载MonkeyLogic数据")
            return True
            
        except Exception as e:
            self.logger.complete_step(step_idx, False, str(e))
            raise DataLoadError(f"MonkeyLogic数据加载失败: {str(e)}")
    
    def _get_file_hash(self, filepath: Path) -> str:
        """计算文件的MD5哈希值（只读取前1MB用于快速比较）"""
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            # 只读取前1MB用于快速比较
            chunk = f.read(1024 * 1024)
            hasher.update(chunk)
            # 加入文件大小和修改时间
            file_stat = filepath.stat()
            hasher.update(str(file_stat.st_size).encode())
            hasher.update(str(file_stat.st_mtime).encode())
        return hasher.hexdigest()
    
    def _load_from_cache(self, cache_file: Path, mat_file: Path) -> bool:
        """
        从缓存文件加载解析后的数据
        
        Args:
            cache_file: 缓存文件路径
            mat_file: 原始mat文件路径
        
        Returns:
            是否成功加载
        """
        try:
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            # 验证缓存有效性
            if not isinstance(cache_data, dict):
                return False
            
            # 检查mat文件是否被修改
            if mat_file.exists():
                current_hash = self._get_file_hash(mat_file)
                cached_hash = cache_data.get('_mat_file_hash', '')
                if current_hash != cached_hash:
                    self.logger.log_info(f"MAT文件已修改，缓存失效")
                    return False
            
            # 检查缓存版本
            cache_version = cache_data.get('_cache_version', '')
            if cache_version != self._get_cache_version():
                self.logger.log_info(f"缓存版本不匹配，缓存失效")
                return False
            
            # 移除元数据字段，获取实际数据
            self.monkeylogic_data = {k: v for k, v in cache_data.items() if not k.startswith('_')}
            self.logger.log_info(f"成功从缓存加载数据: {cache_file}")
            return True
            
        except Exception as e:
            self.logger.log_warning(f"加载缓存失败: {str(e)}")
            return False
    
    def _save_to_cache(self, cache_file: Path, mat_file: Path):
        """
        保存解析后的数据到缓存
        
        Args:
            cache_file: 缓存文件路径
            mat_file: 原始mat文件路径
        """
        try:
            cache_data = self.monkeylogic_data.copy()
            
            # 添加元数据用于验证
            if mat_file.exists():
                cache_data['_mat_file_hash'] = self._get_file_hash(mat_file)
            cache_data['_cache_version'] = self._get_cache_version()
            cache_data['_cache_time'] = pd.Timestamp.now().isoformat()
            
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
            
            self.logger.log_info(f"数据已缓存到: {cache_file}")
            
        except Exception as e:
            self.logger.log_warning(f"保存缓存失败: {str(e)}")
    
    def _get_cache_version(self) -> str:
        """获取缓存版本标识，当解析逻辑改变时应更新"""
        return "v2.2_eye_no_double_transpose"
    
    def clear_cache(self):
        """清除所有缓存文件"""
        processed_dir = self.data_path / "processed"
        if processed_dir.exists():
            for cache_file in processed_dir.glob("*_parsed.pkl"):
                try:
                    cache_file.unlink()
                    self.logger.log_info(f"已删除缓存: {cache_file}")
                except Exception as e:
                    self.logger.log_warning(f"删除缓存失败: {cache_file}, {str(e)}")
    
    def _convert_bhv2_to_mat(self, bhv2_file: Path, mat_file: Path):
        """使用MATLAB引擎将bhv2转换为mat文件"""
        try:
            self.logger.log_info(f"转换{bhv2_file.name}到{mat_file.name}")
            
            # 切换到数据目录
            self.matlab_engine.cd(str(self.data_path), nargout=0)
            
            # 调用mlread函数
            self.matlab_engine.eval(f"trial_ML = mlread('{str(bhv2_file.name)}');", nargout=0)
            
            # 保存为mat文件（使用v7.3格式支持大于2GB的文件）
            self.matlab_engine.eval(f"save('{str(mat_file)}', 'trial_ML', '-v7.3');", nargout=0)
            
            self.logger.log_info(f"成功转换bhv2文件到{mat_file}")
            
        except Exception as e:
            self.logger.log_warning(f"bhv2转换失败: {str(e)}")
            raise
    
    def _load_mat_file(self, mat_file: Path) -> Dict[str, Any]:
        """加载.mat文件，支持v7和v7.3格式"""
        # 优先使用h5py加载v7.3格式
        if H5PY_AVAILABLE:
            try:
                with h5py.File(str(mat_file), 'r') as f:
                    mat_data = self._load_h5py_recursive(f)
                self.logger.log_info("使用h5py成功加载MAT文件(v7.3格式)")
                return self._parse_h5py_mat(mat_data)
            except Exception as e1:
                self.logger.log_warning(f"h5py加载失败: {str(e1)}，尝试scipy.io")
                
                # 回退到scipy.io加载旧的v7格式
                if SCIPY_AVAILABLE:
                    try:
                        mat_data = sio.loadmat(str(mat_file), squeeze_me=True)
                        self.logger.log_info("使用scipy.io成功加载MAT文件(v7格式)")
                        return self._parse_scipy_mat(mat_data)
                    except Exception as e2:
                        raise DataLoadError(f"无法加载MAT文件: h5py={str(e1)}, scipy={str(e2)}")
                else:
                    raise DataLoadError(f"无法加载MAT文件: {str(e1)}")
        
        # 如果h5py不可用，尝试scipy.io
        elif SCIPY_AVAILABLE:
            try:
                mat_data = sio.loadmat(str(mat_file), squeeze_me=True)
                self.logger.log_info("使用scipy.io成功加载MAT文件")
                return self._parse_scipy_mat(mat_data)
            except Exception as e:
                raise DataLoadError(f"无法加载MAT文件(h5py未安装): {str(e)}")
        else:
            raise DataLoadError("SciPy和h5py均未安装，无法加载MAT文件")
    
    def _load_h5py_recursive(self, item) -> Any:
        """递归加载h5py对象"""
        if isinstance(item, h5py.File):
            result = {}
            for key in item.keys():
                if not key.startswith('#'):
                    result[key] = self._load_h5py_recursive(item[key])
            return result
        elif isinstance(item, h5py.Group):
            # 检查是否是struct array
            if 'MATLAB_class' in item.attrs:
                matlab_class = item.attrs['MATLAB_class']
                if isinstance(matlab_class, bytes):
                    matlab_class = matlab_class.decode('utf-8')
                if matlab_class == 'struct':
                    return self._load_h5py_struct(item)
            # 普通group
            result = {}
            for key in item.keys():
                if not key.startswith('#'):
                    result[key] = self._load_h5py_recursive(item[key])
            return result
        elif isinstance(item, h5py.Dataset):
            return self._load_h5py_dataset(item)
        return item
    
    def _load_h5py_dataset(self, dataset: h5py.Dataset) -> Any:
        """加载h5py数据集，确保类型与scipy.io兼容"""
        data = dataset[()]
        
        # 处理对象引用（MATLAB cell array）
        if dataset.dtype == h5py.ref_dtype:
            file_handle = dataset.file
            if isinstance(data, np.ndarray):
                flat_data = data.flatten()
                result = []
                for ref in flat_data:
                    if ref:
                        try:
                            result.append(self._load_h5py_recursive(file_handle[ref]))
                        except:
                            result.append(None)
                    else:
                        result.append(None)
                # 恢复形状
                if len(data.shape) >= 2:
                    try:
                        result = np.array(result, dtype=object).reshape(data.T.shape).T
                    except:
                        pass
                return result
            elif data:
                try:
                    return self._load_h5py_recursive(file_handle[data])
                except:
                    return None
            return None
        
        # 处理MATLAB字符串（uint16编码）
        if data.dtype == np.uint16:
            try:
                chars = data.flatten()
                return ''.join(chr(c) for c in chars if c > 0)
            except:
                return ''
        
        # 处理空数组
        if data.size == 0:
            return np.array([])
        
        # 处理标量 - 关键修复：确保整数类型正确
        if data.shape == () or data.size == 1:
            val = data.item() if hasattr(data, 'item') else data.flat[0]
            return self._normalize_scalar(val)
        
        # 转置（MATLAB是列优先）
        if len(data.shape) >= 2:
            data = data.T
        
        # 规范化数组类型
        return self._normalize_array(np.squeeze(data))
    
    def _normalize_scalar(self, val: Any) -> Any:
        """
        规范化标量值，确保类型与scipy.io兼容
        - 浮点数如果是整数值则转换为int
        - 保持其他类型不变
        """
        if isinstance(val, (np.floating, float)):
            # 检查是否是整数值
            if val == int(val):
                return int(val)
            return float(val)
        elif isinstance(val, (np.integer,)):
            return int(val)
        elif isinstance(val, (np.bool_,)):
            return bool(val)
        return val
    
    def _normalize_array(self, arr: np.ndarray) -> np.ndarray:
        """
        规范化数组类型，确保与scipy.io兼容
        """
        if arr.dtype == object:
            # 对象数组，递归规范化每个元素
            return arr
        
        # 检查浮点数组是否实际上是整数
        if np.issubdtype(arr.dtype, np.floating):
            # 检查所有值是否都是整数
            if arr.size > 0 and np.all(arr == arr.astype(np.int64)):
                return arr.astype(np.int64)
        
        return arr
    
    def _load_h5py_struct(self, group: h5py.Group) -> Any:
        """加载h5py中的MATLAB struct或struct array"""
        keys = [k for k in group.keys() if not k.startswith('#')]
        if not keys:
            return {}
        
        # 检查是否是struct array
        first_item = group[keys[0]]
        if isinstance(first_item, h5py.Dataset) and first_item.dtype == h5py.ref_dtype:
            refs = first_item[()]
            if isinstance(refs, np.ndarray) and refs.size > 1:
                # struct array: 返回列表，每个元素是一个字典
                return self._load_h5py_struct_array(group, refs.shape)
        
        # 普通struct
        result = {}
        for key in keys:
            result[key] = self._load_h5py_recursive(group[key])
        return result
    
    def _load_h5py_struct_array(self, group: h5py.Group, shape: tuple) -> list:
        """加载h5py中的MATLAB struct array为字典列表"""
        keys = [k for k in group.keys() if not k.startswith('#')]
        num_elements = int(np.prod(shape))
        file_handle = group.file
        
        # 收集所有字段数据
        field_data = {}
        for key in keys:
            item = group[key]
            if isinstance(item, h5py.Dataset) and item.dtype == h5py.ref_dtype:
                refs = item[()].flatten()
                field_data[key] = []
                for ref in refs:
                    if ref:
                        try:
                            field_data[key].append(self._load_h5py_recursive(file_handle[ref]))
                        except:
                            field_data[key].append(None)
                    else:
                        field_data[key].append(None)
            else:
                val = self._load_h5py_recursive(item)
                field_data[key] = [val] * num_elements
        
        # 转换为字典列表（每个试次一个字典）
        result = []
        for i in range(num_elements):
            trial_dict = {}
            for key in keys:
                if isinstance(field_data[key], list) and len(field_data[key]) > i:
                    trial_dict[key] = field_data[key][i]
                else:
                    trial_dict[key] = field_data[key]
            result.append(trial_dict)
        
        return result
    
    def _parse_h5py_mat(self, mat_data: Dict) -> Dict[str, Any]:
        """解析h5py加载的.mat文件"""
        trial_ml = mat_data.get('trial_ML', None)
        if trial_ml is not None:
            return self._parse_trial_ml_data(trial_ml)
        else:
            return {k: v for k, v in mat_data.items() if not k.startswith('#')}
    
    def _parse_scipy_mat(self, mat_data: Dict) -> Dict[str, Any]:
        """解析scipy加载的.mat文件"""
        trial_ml = mat_data.get('trial_ML', None)
        if trial_ml is not None:
            return self._parse_trial_ml_data(trial_ml)
        else:
            self.logger.log_warning(f"未找到trial_ML数据: {mat_data.keys()}")
            return {k: v for k, v in mat_data.items() if not k.startswith('__')}
    
    def _parse_trial_ml_data(self, trial_ml) -> Dict[str, Any]:
        """解析trial_ML数据结构，兼容scipy.io和h5py格式"""
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
            # 判断数据格式
            if isinstance(trial_ml, list):
                # h5py格式：字典列表
                trials_list = trial_ml
                num_trials = len(trials_list)
                if num_trials > 0:
                    field_names = list(trials_list[0].keys()) if isinstance(trials_list[0], dict) else []
                else:
                    field_names = []
                is_h5py_format = True
            elif isinstance(trial_ml, np.ndarray) and trial_ml.dtype.names:
                # scipy格式：结构化数组
                trials_list = trial_ml
                num_trials = len(trial_ml)
                field_names = list(trial_ml.dtype.names)
                is_h5py_format = False
            else:
                self.logger.log_warning(f"未知的trial_ML数据类型: {type(trial_ml)}")
                return parsed_data
            
            parsed_data['num_trials'] = num_trials
            self.logger.log_info(f"解析{num_trials}个试次的MonkeyLogic数据")
            self.logger.log_info(f"可用字段: {field_names}")
            self.logger.log_info(f"数据格式: {'h5py(列表)' if is_h5py_format else 'scipy(结构化数组)'}")
            
            if num_trials > 0:
                # 解析Trial字段
                if 'Trial' in field_names:
                    parsed_data['Trial'] = self._extract_simple_field(trials_list, 'Trial', is_h5py_format, int)
                
                # 解析AbsoluteTrialStartTime字段
                abs_start_times = []
                if 'AbsoluteTrialStartTime' in field_names:
                    abs_start_times = self._extract_simple_field(trials_list, 'AbsoluteTrialStartTime', is_h5py_format, float)
                
                # 解析BehavioralCodes字段
                if 'BehavioralCodes' in field_names:
                    parsed_data['BehavioralCodes'] = self._extract_behavioral_codes_all_trials(trials_list, is_h5py_format)
                
                # 解析AnalogData字段
                if 'AnalogData' in field_names:
                    parsed_data['AnalogData'] = self._extract_analog_data_all_trials(trials_list, is_h5py_format)
                
                # 解析UserVars字段
                if 'UserVars' in field_names:
                    parsed_data['UserVars'] = self._extract_user_vars_all_trials(trials_list, is_h5py_format)
                
                # 解析VariableChanges字段
                if 'VariableChanges' in field_names:
                    parsed_data['VariableChanges'] = self._extract_variable_changes_all_trials(trials_list, is_h5py_format)
                
                # 计算duration
                try:
                    if abs_start_times and parsed_data['BehavioralCodes'].get('CodeTimes'):
                        last_code_times = parsed_data['BehavioralCodes']['CodeTimes'][-1]
                        if isinstance(last_code_times, (list, np.ndarray)) and len(last_code_times) > 0:
                            last_time = last_code_times[-1] if hasattr(last_code_times, '__getitem__') else last_code_times
                            parsed_data['duration'] = (abs_start_times[-1] + float(last_time)) / 1000
                        elif isinstance(last_code_times, (int, float)):
                            parsed_data['duration'] = (abs_start_times[-1] + last_code_times) / 1000
                except Exception as e:
                    self.logger.log_warning(f"计算duration失败: {str(e)}")
            
            self.logger.log_info("MonkeyLogic数据解析完成")
        
        except Exception as e:
            self.logger.log_warning(f"解析trial_ML数据失败: {str(e)}")
            import traceback
            self.logger.log_warning(traceback.format_exc())
            
        return parsed_data
    
    def _extract_simple_field(self, trials_list, field_name: str, is_h5py: bool, dtype_func=None) -> list:
        """提取简单字段（标量值），并进行类型规范化"""
        result = []
        try:
            for i, trial in enumerate(trials_list):
                try:
                    if is_h5py:
                        # h5py格式：字典
                        val = trial.get(field_name)
                    else:
                        # scipy格式：结构化数组
                        val = trials_list[field_name][i]
                        if isinstance(val, np.ndarray):
                            val = val.item() if val.size == 1 else val.flatten()[0]
                    
                    # 规范化值
                    val = self._normalize_value(val)
                    
                    if dtype_func and val is not None:
                        val = dtype_func(val)
                    result.append(val)
                except Exception as e:
                    result.append(None)
        except Exception as e:
            self.logger.log_warning(f"提取字段{field_name}失败: {str(e)}")
        return result
    
    def _normalize_value(self, val: Any) -> Any:
        """
        规范化值，确保类型与scipy.io兼容
        - 浮点数如果是整数值则转换为int
        - numpy类型转换为Python原生类型
        - 递归处理列表和数组
        """
        if val is None:
            return None
        
        # 处理numpy标量
        if isinstance(val, (np.floating, float)):
            # 检查是否是整数值
            if np.isfinite(val) and val == int(val):
                return int(val)
            return float(val)
        elif isinstance(val, (np.integer,)):
            return int(val)
        elif isinstance(val, (np.bool_,)):
            return bool(val)
        elif isinstance(val, np.ndarray):
            # 数组类型规范化
            if val.size == 0:
                return []
            if val.size == 1:
                return self._normalize_value(val.item())
            # 对于较小的数组，转换为列表并规范化
            if val.size <= 1000:
                return [self._normalize_value(v) for v in val.flatten()]
            # 大数组保持numpy格式但规范化dtype
            return self._normalize_array(val)
        elif isinstance(val, list):
            return [self._normalize_value(v) for v in val]
        
        return val
    
    def _extract_behavioral_codes_all_trials(self, trials_list, is_h5py: bool) -> Dict[str, Any]:
        """提取所有试次的行为代码，确保每个试次的 CodeTimes 和 CodeNumbers 都是列表"""
        behavioral_codes = {
            'CodeTimes': [],
            'CodeNumbers': []
        }
        
        try:
            num_trials = len(trials_list)
            for i in range(num_trials):
                try:
                    if is_h5py:
                        # h5py格式：字典
                        trial = trials_list[i]
                        bc = trial.get('BehavioralCodes', {})
                        if isinstance(bc, dict):
                            code_times = bc.get('CodeTimes', [])
                            code_numbers = bc.get('CodeNumbers', [])
                        else:
                            code_times = []
                            code_numbers = []
                    else:
                        # scipy格式：结构化数组
                        bc = trials_list['BehavioralCodes'][i]
                        if hasattr(bc, 'dtype') and bc.dtype.names:
                            code_times = bc['CodeTimes'].flatten() if 'CodeTimes' in bc.dtype.names and bc['CodeTimes'].size > 0 else []
                            code_numbers = bc['CodeNumbers'].flatten() if 'CodeNumbers' in bc.dtype.names and bc['CodeNumbers'].size > 0 else []
                            # 处理嵌套
                            if isinstance(code_times, np.ndarray) and code_times.dtype == object:
                                code_times = code_times.item() if code_times.size == 1 else code_times
                            if isinstance(code_numbers, np.ndarray) and code_numbers.dtype == object:
                                code_numbers = code_numbers.item() if code_numbers.size == 1 else code_numbers
                        else:
                            code_times = []
                            code_numbers = []
                    
                    # 统一转换为列表格式
                    code_times = self._ensure_list(code_times)
                    code_numbers = self._ensure_list(code_numbers)
                    
                    behavioral_codes['CodeTimes'].append(code_times)
                    behavioral_codes['CodeNumbers'].append(code_numbers)
                    
                except Exception as e:
                    self.logger.log_warning(f"提取试次{i}行为代码失败: {str(e)}")
                    behavioral_codes['CodeTimes'].append([])
                    behavioral_codes['CodeNumbers'].append([])
                    
        except Exception as e:
            self.logger.log_warning(f"提取行为代码失败: {str(e)}")
            
        return behavioral_codes
    
    def _ensure_list(self, val: Any) -> list:
        """
        确保值是列表格式，处理各种边界情况
        - None -> []
        - 标量 -> [标量]
        - 0d numpy数组 -> [标量]
        - 1d numpy数组 -> 列表
        - 已经是列表 -> 原样返回
        """
        if val is None:
            return []
        
        # 处理 numpy 数组
        if isinstance(val, np.ndarray):
            # 0d 数组（标量）
            if val.ndim == 0:
                return [self._normalize_scalar(val.item())]
            # 空数组
            if val.size == 0:
                return []
            # 正常数组
            return [self._normalize_scalar(v) if np.isscalar(v) else v for v in val.flatten().tolist()]
        
        # 已经是列表
        if isinstance(val, list):
            return val
        
        # numpy 标量类型
        if isinstance(val, (np.integer, np.floating)):
            return [self._normalize_scalar(val)]
        
        # Python 标量
        if isinstance(val, (int, float)):
            return [val]
        
        # 其他情况，尝试转换
        try:
            return list(val)
        except (TypeError, ValueError):
            return [val] if val else []
    
    def _extract_analog_data_all_trials(self, trials_list, is_h5py: bool) -> Dict[str, Any]:
        """提取所有试次的模拟数据"""
        analog_data = {
            'Eye': [],
            'SampleInterval': []
        }
        
        try:
            num_trials = len(trials_list)
            for i in range(num_trials):
                try:
                    if is_h5py:
                        # h5py格式
                        trial = trials_list[i]
                        ad = trial.get('AnalogData', {})
                        if isinstance(ad, dict):
                            eye_data = ad.get('Eye')
                            sample_interval = ad.get('SampleInterval', 1.0)
                        else:
                            eye_data = None
                            sample_interval = 1.0
                    else:
                        # scipy格式
                        ad = trials_list['AnalogData'][i]
                        if hasattr(ad, 'dtype') and ad.dtype.names:
                            eye_data = ad['Eye'].item() if 'Eye' in ad.dtype.names and ad['Eye'].size > 0 else None
                            sample_interval = float(ad['SampleInterval'].item()) if 'SampleInterval' in ad.dtype.names else 1.0
                        else:
                            eye_data = None
                            sample_interval = 1.0
                    
                    # eye_data 已在 _load_h5py_dataset 中正确转置为 (N, 2)，此处无需再转置
                    analog_data['Eye'].append(eye_data)
                    analog_data['SampleInterval'].append(float(sample_interval) if sample_interval else 1.0)
                    
                except Exception as e:
                    self.logger.log_warning(f"提取试次{i}模拟数据失败: {str(e)}")
                    analog_data['Eye'].append(None)
                    analog_data['SampleInterval'].append(1.0)
                    
        except Exception as e:
            self.logger.log_warning(f"提取模拟数据失败: {str(e)}")
            
        return analog_data
    
    def _extract_user_vars_all_trials(self, trials_list, is_h5py: bool) -> Dict[str, Any]:
        """提取所有试次的用户变量，并进行类型规范化"""
        user_vars = {}
        
        try:
            num_trials = len(trials_list)
            # 先确定所有可能的字段
            all_fields = set()
            for i in range(min(10, num_trials)):  # 检查前10个试次
                try:
                    if is_h5py:
                        uv = trials_list[i].get('UserVars', {})
                        if isinstance(uv, dict):
                            all_fields.update(uv.keys())
                    else:
                        uv = trials_list['UserVars'][i]
                        if hasattr(uv, 'dtype') and uv.dtype.names:
                            all_fields.update(uv.dtype.names)
                except:
                    pass
            
            # 初始化字段
            for field in all_fields:
                user_vars[field] = []
            
            # 提取数据
            for i in range(num_trials):
                try:
                    if is_h5py:
                        uv = trials_list[i].get('UserVars', {})
                        for field in all_fields:
                            val = uv.get(field) if isinstance(uv, dict) else None
                            # 规范化值（但不对大数组做转换以保持性能）
                            if not isinstance(val, np.ndarray) or val.size <= 100:
                                val = self._normalize_value(val)
                            user_vars[field].append(val)
                    else:
                        uv = trials_list['UserVars'][i]
                        for field in all_fields:
                            if hasattr(uv, 'dtype') and uv.dtype.names and field in uv.dtype.names:
                                val = uv[field]
                                if isinstance(val, np.ndarray):
                                    val = val.item() if val.size == 1 else val.flatten()
                                user_vars[field].append(val)
                            else:
                                user_vars[field].append(None)
                except Exception as e:
                    for field in all_fields:
                        user_vars[field].append(None)
                        
        except Exception as e:
            self.logger.log_warning(f"提取用户变量失败: {str(e)}")
            
        return user_vars
    
    def _extract_variable_changes_all_trials(self, trials_list, is_h5py: bool) -> Dict[str, Any]:
        """提取所有试次的变量变化，并进行类型规范化"""
        variable_changes = {}
        
        try:
            num_trials = len(trials_list)
            # 先确定所有可能的字段
            all_fields = set()
            for i in range(min(10, num_trials)):
                try:
                    if is_h5py:
                        vc = trials_list[i].get('VariableChanges', {})
                        if isinstance(vc, dict):
                            all_fields.update(vc.keys())
                    else:
                        vc = trials_list['VariableChanges'][i]
                        if hasattr(vc, 'dtype') and vc.dtype.names:
                            all_fields.update(vc.dtype.names)
                except:
                    pass
            
            # 初始化字段
            for field in all_fields:
                variable_changes[field] = []
            
            # 提取数据
            for i in range(num_trials):
                try:
                    if is_h5py:
                        vc = trials_list[i].get('VariableChanges', {})
                        for field in all_fields:
                            val = vc.get(field) if isinstance(vc, dict) else None
                            # 规范化值
                            val = self._normalize_value(val)
                            variable_changes[field].append(val)
                    else:
                        vc = trials_list['VariableChanges'][i]
                        for field in all_fields:
                            if hasattr(vc, 'dtype') and vc.dtype.names and field in vc.dtype.names:
                                val = vc[field]
                                if isinstance(val, np.ndarray):
                                    val = val.item() if val.size == 1 else val.flatten()
                                # 规范化值
                                val = self._normalize_value(val)
                                variable_changes[field].append(val)
                            else:
                                variable_changes[field].append(None)
                except Exception as e:
                    for field in all_fields:
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