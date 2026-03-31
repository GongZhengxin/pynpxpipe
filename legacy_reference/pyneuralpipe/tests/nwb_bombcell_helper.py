"""
NWB Bombcell集成工具
用于将Bombcell质量指标集成到NWB文件中
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from pathlib import Path

def create_bombcell_compound_dtype():
    """
    创建Bombcell质量指标的复合数据类型
    
    Returns:
        np.dtype: 包含所有Bombcell质量指标的复合数据类型
    """
    quality_metrics_dtype = np.dtype([
        ('phy_clusterID', np.int32),
        ('nSpikes', np.int32),
        ('nPeaks', np.int32),
        ('nTroughs', np.int32),
        ('waveformDuration_peakTrough', np.float64),
        ('spatialDecaySlope', np.float64),
        ('waveformBaselineFlatness', np.float64),
        ('scndPeakToTroughRatio', np.float64),
        ('mainPeakToTroughRatio', np.float64),
        ('peak1ToPeak2Ratio', np.float64),
        ('troughToPeak2Ratio', np.float64),
        ('mainPeak_before_width', np.float64),
        ('mainTrough_width', np.float64),
        ('percentageSpikesMissing_gaussian', np.float64),
        ('percentageSpikesMissing_symmetric', np.float64),
        ('RPV_window_index', np.float64),
        ('fractionRPVs_estimatedTauR', np.float64),
        ('presenceRatio', np.float64),
        ('maxDriftEstimate', np.float64),
        ('cumDriftEstimate', np.float64),
        ('rawAmplitude', np.float64),
        ('signalToNoiseRatio', np.float64),
        ('isolationDistance', np.float64),
        ('Lratio', np.float64),
        ('silhouetteScore', np.float64),
        ('useTheseTimesStart', np.float64),
        ('useTheseTimesStop', np.float64),
        ('maxChannels', np.int32)
    ])
    
    return quality_metrics_dtype

def get_bombcell_metrics_descriptions():
    """
    获取Bombcell质量指标的描述字典
    
    Returns:
        Dict[str, str]: 质量指标名称到描述的映射
    """
    return {
        'phy_clusterID': 'Unique identifier for each cluster/unit from Phy spike sorting',
        'nSpikes': 'Total number of spikes detected for this unit',
        'nPeaks': 'Number of peaks detected in the template waveform',
        'nTroughs': 'Number of troughs detected in the template waveform', 
        'waveformDuration_peakTrough': 'Duration between peak and trough in the template waveform (microseconds)',
        'spatialDecaySlope': 'Slope of the spatial decay of the waveform amplitude across channels',
        'waveformBaselineFlatness': 'Measure of baseline flatness in the template waveform',
        'scndPeakToTroughRatio': 'Ratio between the repolarization (second) peak and main trough amplitude',
        'mainPeakToTroughRatio': 'Ratio between the main peak and main trough amplitude', 
        'peak1ToPeak2Ratio': 'Ratio between the first peak and repolarization (second) peak amplitude',
        'troughToPeak2Ratio': 'Ratio between main trough and repolarization (second) peak amplitude',
        'mainPeak_before_width': 'Width of the main peak before the trough (samples)',
        'mainTrough_width': 'Width of the main trough (samples)',
        'percentageSpikesMissing_gaussian': 'Percentage of spikes estimated to be missing based on Gaussian distribution',
        'percentageSpikesMissing_symmetric': 'Percentage of spikes estimated to be missing based on symmetric distribution',
        'RPV_window_index': 'Index of the refractory period violation window used for analysis',
        'fractionRPVs_estimatedTauR': 'Fraction of refractory period violations with estimated refractory period',
        'presenceRatio': 'Fraction of the session during which the unit was present and active',
        'maxDriftEstimate': 'Maximum estimated drift of the unit during the recording session',
        'cumDriftEstimate': 'Cumulative estimated drift of the unit during the recording session',
        'rawAmplitude': 'Mean amplitude of the raw waveform (microvolts)',
        'signalToNoiseRatio': 'Signal-to-noise ratio of the unit template',
        'isolationDistance': 'Isolation distance metric measuring cluster separation in feature space',
        'Lratio': 'L-ratio metric measuring cluster isolation quality',
        'silhouetteScore': 'Silhouette score measuring how well-separated the cluster is',
        'useTheseTimesStart': 'Start time (samples) of the analysis window for this unit',
        'useTheseTimesStop': 'Stop time (samples) of the analysis window for this unit',
        'maxChannels': 'Channel with maximum amplitude for this unit template'
    }

def add_bombcell_column_to_units(nwbfile, method='compound'):
    """
    在NWB文件的units表中添加Bombcell质量指标列
    
    Args:
        nwbfile: NWB文件对象
        method: 存储方法 ('compound', 'separate', 'json')
    """
    if method == 'compound':
        # 方案1：使用复合数据类型
        quality_dtype = create_bombcell_compound_dtype()
        nwbfile.add_unit_column(
            name='bc_qm',
            description='Bombcell quality metrics as compound data type',
            data=[]  # 将在添加unit时填充
        )
        
    elif method == 'separate':
        # 方案2：为每个指标创建单独的列
        descriptions = get_bombcell_metrics_descriptions()
        for metric_name, description in descriptions.items():
            nwbfile.add_unit_column(
                name=f'bc_{metric_name}',
                description=description,
                data=[]
            )
    
    elif method == 'json':
        # 方案3：使用JSON字符串
        nwbfile.add_unit_column(
            name='bc_qm_json',
            description='Bombcell quality metrics as JSON string',
            data=[]
        )

def convert_bombcell_df_to_nwb_format(bc_qm_df: pd.DataFrame, method='compound'):
    """
    将Bombcell质量指标DataFrame转换为NWB格式
    
    Args:
        bc_qm_df: Bombcell质量指标DataFrame
        method: 转换方法 ('compound', 'separate', 'json')
        
    Returns:
        适合NWB存储的数据格式
    """
    if method == 'compound':
        # 转换为复合数据类型数组
        quality_dtype = create_bombcell_compound_dtype()
        quality_data = []
        
        for idx, row in bc_qm_df.iterrows():
            # 创建符合复合数据类型的元组
            quality_tuple = tuple(
                row.get(field_name, np.nan) if field_type != np.int32 
                else int(row.get(field_name, 0))
                for field_name, field_type in quality_dtype.descr
            )
            quality_data.append(quality_tuple)
        
        return np.array(quality_data, dtype=quality_dtype)
    
    elif method == 'separate':
        # 返回每个指标的单独数组
        return {col: bc_qm_df[col].values for col in bc_qm_df.columns}
    
    elif method == 'json':
        # 转换为JSON字符串列表
        import json
        return [json.dumps(row.to_dict()) for idx, row in bc_qm_df.iterrows()]

def add_units_with_bombcell_metrics(nwbfile, spike_times_list, bc_qm_df, method='compound'):
    """
    添加包含Bombcell质量指标的units到NWB文件
    
    Args:
        nwbfile: NWB文件对象
        spike_times_list: 每个unit的spike times列表
        bc_qm_df: Bombcell质量指标DataFrame
        method: 存储方法
    """
    # 首先添加列
    add_bombcell_column_to_units(nwbfile, method)
    
    # 转换数据格式
    bc_data = convert_bombcell_df_to_nwb_format(bc_qm_df, method)
    
    # 添加units
    for i, spike_times in enumerate(spike_times_list):
        unit_kwargs = {'spike_times': spike_times}
        
        if method == 'compound':
            unit_kwargs['bc_qm'] = bc_data[i] if i < len(bc_data) else None
        elif method == 'separate':
            for metric_name in bc_qm_df.columns:
                unit_kwargs[f'bc_{metric_name}'] = bc_data[metric_name][i] if i < len(bc_data[metric_name]) else np.nan
        elif method == 'json':
            unit_kwargs['bc_qm_json'] = bc_data[i] if i < len(bc_data) else "{}"
        
        nwbfile.add_unit(**unit_kwargs)

# 使用示例
def example_usage():
    """使用示例"""
    from pynwb import NWBFile
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    # 创建NWB文件
    nwbfile = NWBFile(
        session_description='Spike sorting with Bombcell quality control',
        identifier='example_session',
        session_start_time=datetime.now(ZoneInfo('UTC'))
    )
    
    # 加载Bombcell数据
    bc_path = Path('path/to/bombcell/output')
    bc_qm_df = pd.read_csv(bc_path / 'templates._bc_qMetrics.csv', index_col=0)
    
    # 模拟spike times数据
    spike_times_list = [
        np.array([0.1, 0.2, 0.3, 0.4]),
        np.array([0.15, 0.25, 0.35]),
        # ... 更多units
    ]
    
    # 添加units和质量指标
    add_units_with_bombcell_metrics(nwbfile, spike_times_list, bc_qm_df, method='compound')
    
    return nwbfile
