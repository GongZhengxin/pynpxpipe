"""
目录检查模块

检查数据目录结构并确定处理阶段
"""

import os
import glob
from pathlib import Path
from typing import Dict, List, Optional
from enum import Enum


class ProcessingStage(Enum):
    """处理阶段枚举"""
    DATA_CHECK = "Data Check"
    SPIKE_SORTING = "Spike Sorting"
    POST_PROCESS = "Post Process"
    COMPLETED = "Completed"


class DirectoryChecker:
    """
    目录检查器类
    
    用于检查神经数据目录结构并确定当前处理阶段
    """
    
    def __init__(self):
        self.required_files = {
            'spikeglx': ['.ap.bin', '.ap.meta', '.lf.bin', '.lf.meta'],
            'monkeylogic': ['.bhv2'],
            'kilosort': ['spike_times.npy', 'spike_clusters.npy', 'templates.npy']
        }
    
    def check_directory_structure(self, data_path: str) -> Dict:
        """
        检查数据目录结构并确定处理阶段
        
        Args:
            data_path: 数据目录路径
            
        Returns:
            dict: 包含检查结果和当前阶段的字典
            {
                'status': 'valid'|'invalid'|'warning',
                'stage': ProcessingStage,
                'details': {
                    'spikeglx_found': bool,
                    'monkeylogic_found': bool,
                    'kilosort_found': bool,
                    'missing_files': list,
                    'extra_files': list
                },
                'message': str
            }
        """
        if not os.path.exists(data_path):
            return {
                'status': 'invalid',
                'stage': ProcessingStage.DATA_CHECK,
                'details': {},
                'message': f'目录不存在: {data_path}'
            }
        
        path = Path(data_path)
        details = self._scan_directory(path)
        
        # 确定处理阶段
        stage = self._determine_stage(details)
        
        # 确定状态
        status = self._determine_status(details)
        
        # 生成消息
        message = self._generate_message(details, stage)
        
        return {
            'status': status,
            'stage': stage,
            'details': details,
            'message': message
        }
    
    def _scan_directory(self, path: Path) -> Dict:
        """扫描目录内容"""
        details = {
            'spikeglx_found': False,
            'monkeylogic_found': False,
            'kilosort_found': False,
            'nwb_found': False,
            'missing_files': [],
            'extra_files': [],
            'file_list': []
        }
        
        # 获取所有文件
        all_files = []
        for file_path in path.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(path)
                all_files.append(str(relative_path))
        
        details['file_list'] = all_files
        
        # 检查SpikeGLX文件
        details['spikeglx_found'] = self._check_spikeglx_files(all_files)
        
        # 检查MonkeyLogic文件
        details['monkeylogic_found'] = self._check_monkeylogic_files(all_files)
        
        # 检查Kilosort输出文件
        details['kilosort_found'] = self._check_kilosort_files(all_files)
        
        # 检查NWB文件
        details['nwb_found'] = self._check_nwb_files(all_files)
        
        return details
    
    def _check_spikeglx_files(self, file_list: List[str]) -> bool:
        """检查SpikeGLX文件是否存在"""
        required_extensions = self.required_files['spikeglx']
        found_extensions = set()
        
        for file_path in file_list:
            for ext in required_extensions:
                if file_path.endswith(ext):
                    found_extensions.add(ext)
        
        # 至少需要找到.ap.bin和.ap.meta文件
        return '.ap.bin' in found_extensions and '.ap.meta' in found_extensions
    
    def _check_monkeylogic_files(self, file_list: List[str]) -> bool:
        """检查MonkeyLogic文件是否存在"""
        return any(file_path.endswith('.bhv2') for file_path in file_list)
    
    def _check_kilosort_files(self, file_list: List[str]) -> bool:
        """检查Kilosort输出文件是否存在"""
        required_files = self.required_files['kilosort']
        found_files = 0
        
        for file_path in file_list:
            file_name = os.path.basename(file_path)
            if file_name in required_files:
                found_files += 1
        
        return found_files >= 2  # 至少需要找到2个必需文件
    
    def _check_nwb_files(self, file_list: List[str]) -> bool:
        """检查NWB文件是否存在"""
        return any(file_path.endswith('.nwb') for file_path in file_list)
    
    def _determine_stage(self, details: Dict) -> ProcessingStage:
        """根据检查结果确定处理阶段"""
        if details['nwb_found']:
            return ProcessingStage.COMPLETED
        elif details['kilosort_found']:
            return ProcessingStage.POST_PROCESS
        elif details['spikeglx_found'] and details['monkeylogic_found']:
            return ProcessingStage.SPIKE_SORTING
        else:
            return ProcessingStage.DATA_CHECK
    
    def _determine_status(self, details: Dict) -> str:
        """确定目录状态"""
        if not details['spikeglx_found']:
            return 'invalid'
        elif not details['monkeylogic_found']:
            return 'warning'
        else:
            return 'valid'
    
    def _generate_message(self, details: Dict, stage: ProcessingStage) -> str:
        """生成状态消息"""
        messages = []
        
        if not details['spikeglx_found']:
            messages.append("❌ 未找到SpikeGLX数据文件(.ap.bin, .ap.meta)")
        else:
            messages.append("✅ SpikeGLX数据文件已找到")
        
        if not details['monkeylogic_found']:
            messages.append("⚠️ 未找到MonkeyLogic行为数据(.bhv2)")
        else:
            messages.append("✅ MonkeyLogic行为数据已找到")
        
        if details['kilosort_found']:
            messages.append("✅ Kilosort输出文件已找到")
        
        if details['nwb_found']:
            messages.append("✅ NWB文件已存在")
        
        messages.append(f"\n当前阶段: {stage.value}")
        
        return "\n".join(messages)
    
    def get_processing_recommendations(self, check_result: Dict) -> List[str]:
        """
        根据检查结果提供处理建议
        
        Args:
            check_result: directory_checker的输出结果
            
        Returns:
            处理建议列表
        """
        recommendations = []
        stage = check_result['stage']
        details = check_result['details']
        
        if stage == ProcessingStage.DATA_CHECK:
            if not details['spikeglx_found']:
                recommendations.append("请确保目录中包含SpikeGLX数据文件(.ap.bin, .ap.meta)")
            if not details['monkeylogic_found']:
                recommendations.append("建议添加MonkeyLogic行为数据文件(.bhv2)以进行完整分析")
        
        elif stage == ProcessingStage.SPIKE_SORTING:
            recommendations.append("可以开始运行Kilosort进行尖峰排序")
            recommendations.append("建议检查数据质量和参数设置")
        
        elif stage == ProcessingStage.POST_PROCESS:
            recommendations.append("可以进行质量控制和神经元筛选")
            recommendations.append("可以计算PSTH和响应分析")
            recommendations.append("可以导出NWB和MAT文件")
        
        elif stage == ProcessingStage.COMPLETED:
            recommendations.append("处理已完成，可以进行进一步分析")
            recommendations.append("可以进行云备份或数据共享")
        
        return recommendations
