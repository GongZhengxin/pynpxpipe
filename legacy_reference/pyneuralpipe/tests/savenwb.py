#写出为 NWB 文件
from datetime import datetime
import mmap
from zoneinfo import ZoneInfo
from pathlib import Path
from dateutil import tz
import h5py
import numpy as np
import pandas as pd
import warnings
import sys
from tqdm import tqdm
sys.path.append(fr'F:\ProcessPipeline\pyneuralpipe')
from utils.nwb_stim_helper import StimulusImageManager


# NWB 相关导入
import pynwb
from pynwb import NWBHDF5IO
from pynwb.file import Subject
from pynwb.behavior import Position, SpatialSeries, EyeTracking
from pynwb.base import TimeSeries
from pynwb.epoch import TimeIntervals
from pynwb.ecephys import ElectricalSeries
from pynwb.file import ElectrodeTable
from pynwb.image import ImageSeries
from pynwb.base import Images

# NeuroConv 相关导入
from neuroconv.converters import SpikeGLXConverterPipe
from neuroconv.datainterfaces import KiloSortSortingInterface
from neuroconv.tools.nwb_helpers import get_default_backend_configuration
from neuroconv.utils.dict import load_dict_from_file, dict_deep_update

# path preparation
data_path = Path(fr"F:\ProcessPipeline\testdata\wordfob")
output_folder = Path(fr'F:\ProcessPipeline\nwbfiles')
nwbfile_path = output_folder / "testsesison_1001.nwb"

# Step 1 make raw data converter & convert to NWB on disk
# ================================
spikeglx_path = data_path / "NPX_MD241029_exp_g0"
converter = SpikeGLXConverterPipe(folder_path=spikeglx_path, verbose=True)

# Extract what metadata we can from the source files
metadata = converter.get_metadata()

# For data provenance we add the time zone information to the conversion
session_start_time = metadata["NWBFile"]["session_start_time"].replace(tzinfo=tz.tzlocal())
metadata["NWBFile"].update(session_start_time=session_start_time)
# metadata["Ecephys"]["ElectrodeGroup"][0]["location"] = "MLO"
# Create the in-memory NWBFile object and retrieve a default configuration for the backend
nwbfile = converter.create_nwbfile(metadata=metadata)
backend_configurations = get_default_backend_configuration(
    nwbfile=nwbfile,
    backend="hdf5",
)
# Set the comrpession method to AP & LFP
dataset_configurations = backend_configurations.dataset_configurations
# ap config
ap_config = dataset_configurations["acquisition/ElectricalSeriesAP/data"]
ap_config.chunk_shape = (1, 64)
ap_config.buffer_shape = (200000, 384)
ap_config.chunk_shape = (40000, 64)
ap_config.compression_method = "Blosc"
ap_config.compression_options = {"cname": "zstd", "clevel": 6}
# lf config
lf_config = dataset_configurations["acquisition/ElectricalSeriesLF/data"]
lf_config.chunk_shape = (40000, 64)
lf_config.compression_method = "Blosc"
lf_config.compression_options = {"cname": "zstd", "clevel": 6}
# conversion options
conversion_options = {
    "imec0.ap": {"stub_test": False, 
                "iterator_opts":dict(
                display_progress=True  # Show progress bar
                ),
        },
    "imec0.lf": {"stub_test": False,
                "iterator_opts":dict(
                display_progress=True  # Show progress bar
                ),},
}

# update metadata & subject metadata into existed nwb_file
# session template from yaml & update
metadata_path = fr"F:\ProcessPipeline\pyneuralpipe\config\nwb_template.yaml"
metadata_from_yaml = load_dict_from_file(file_path=metadata_path)
metadata = dict_deep_update(metadata_from_yaml, metadata)

# subject template from yaml & update
subject_path = fr"F:\ProcessPipeline\pyneuralpipe\config\MaoDan.yaml"
subject_from_yaml = load_dict_from_file(file_path=subject_path)
metadata = dict_deep_update(subject_from_yaml, metadata)

# update electrode group location
metadata["Ecephys"]["ElectrodeGroup"][0]["location"] = "MLO"

# run conversion
if nwbfile_path.exists():
    print('nwbfile already exists')
else:
    converter.run_conversion(nwbfile_path=nwbfile_path, metadata=metadata,
                            conversion_options=conversion_options,
                            backend_configuration=backend_configurations)


# Step 2 writing kilosort results into existed nwb_file as processing module
# ================================
if (nwbfile.processing and 
    'ecephys' in nwbfile.processing and
    'kilosort4_unit' in nwbfile.processing['ecephys'].data_interfaces):
    print('kilosort4_unit already in nwb file')
else:
    ks_path = data_path / 'processed' / 'kilosort_output' / 'sorter_output'
    with NWBHDF5IO(nwbfile_path, 'r+') as io:
        nwbfile = io.read()
        # add kilosort results to nwb file
        ks_interface = KiloSortSortingInterface(folder_path=ks_path, verbose=True)
        # conversion options
        ks_conversion_options = { 
            'write_as': 'processing',
            'units_name' : 'kilosort4_unit',
        }
        ks_interface.add_to_nwbfile(nwbfile,**ks_conversion_options)
        io.write(nwbfile)


# Step 3 writing trial events / eye tracking / stimulus data into existed nwb_file
# ================================
meta_file_path = data_path / 'processed' / 'META_wordfob.h5'
with h5py.File(meta_file_path, 'r') as f:
    stim_start_times = f['sync_info']['stim_start_times'][:] / 1000 # convert to second
    stim_end_times = f['sync_info']['stim_end_times'][:] / 1000 # convert to second
    trial_valid_idx = f['trial_validation']['trial_valid_idx'][:].astype(np.int64)
    dataset_valid_idx = f['trial_validation']['dataset_valid_idx'][:]
    eye_track = f['eye_data']['eye_matrix'][:]
    stim_path = f['session_info'].attrs['dataset_path']
    stim_dataset_name = f['session_info'].attrs['dataset_name']
image_names = pd.read_csv(stim_path, sep='\t').FileName.values
image_names = np.insert(image_names, 0, 'None')
trial_stim_names = image_names[trial_valid_idx]

with NWBHDF5IO(nwbfile_path, "r+") as io:
    nwbfile = io.read()
    # 创建新列
    new_clols = {
        'stim_index' : 'stimulus matlab index (1-indexed)', 
        'stim_name' : 'stimulus name',
        'fix_success' : 'whether the fixation was successful'
        }
    for col_name, col_description in new_clols.items():
        nwbfile.add_trial_column(
                    name=col_name,
                    description=col_description
                )
    # add trial data to nwb file
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
    for i, trial_data in tqdm(enumerate(all_trial_data), total=n_trials, desc="Adding trial data:"):
        nwbfile.add_trial(**trial_data)
        
    # writing eye tracking data into existed nwb_file
    n_timetpoint = eye_track.shape[1]
    interval = 0.001 # second
    eyetrack_start_times = np.asarray(stim_start_times).reshape(-1, 1)
    eyetrack_timestamp = eyetrack_start_times + np.arange(n_timetpoint) * interval
    eyetrack_timestamp = eyetrack_timestamp.reshape(-1)
    eye_track = eye_track.reshape((-1, 2))
    behavior_module = nwbfile.create_processing_module(
        name="behavior", description="Processed behavioral data"
    )
    # only use right eye tracking data
    right_eye_positions = SpatialSeries(
        name="right_eye_position",
        description="The position of the right eye measured in degrees.",
        data=eye_track,
        timestamps=eyetrack_timestamp,
        reference_frame="center of screen",
        unit="degrees",
    )
    eye_tracking = EyeTracking(name="EyeTracking", spatial_series=right_eye_positions)
    behavior_module.add(eye_tracking)

    # writing stimulus data into existed nwb_file
    stim_manager = StimulusImageManager(stim_path)
    images_series, index_series = stim_manager.add_to_nwb(
        nwbfile, trial_valid_idx, stim_start_times,
        stimulus_name=stim_dataset_name
    )
    io.write(nwbfile)


# Step 5 writing custom unit into existed nwb_file
# ================================
# 获取现有的 unit 和 trial
with NWBHDF5IO(nwbfile_path, 'r') as io:
    nwbfile = io.read()
    unit_df = nwbfile.processing['ecephys']['kilosort4_unit'].to_dataframe()
    trial_df = nwbfile.trials.to_dataframe()
spike_times_list = unit_df['spike_times'].values
bc_unittype_string = unit_df['bc_unitType'].values
n_units = len(spike_times_list)

# unit pos from sorting
spike_pos = np.load(ks_path / 'spike_positions.npy', mmap_mode='r')
spike_template = np.load(ks_path / 'spike_templates.npy', mmap_mode='r')

# waveform / unittype / some metrics are from bc
bc_path = data_path /'processed' / 'bombcell'
bc_qm_df = pd.read_csv(bc_path / 'templates._bc_qMetrics.csv', index_col=0)

# 删除全为 NaN 的列
nan_cols = bc_qm_df.columns[bc_qm_df.isna().all()].tolist()
if nan_cols:
    print(f"删除 {len(nan_cols)} 个全为 NaN 的列: {nan_cols}")
    bc_qm_df = bc_qm_df.drop(columns=nan_cols)

waveform = np.load(bc_path / 'templates._bc_rawWaveforms.npy')
max_channels = np.load(bc_path / 'templates._bc_rawWaveformPeakChannels.npy')
saved_waveform = []
for max_channel in max_channels: 
    near_channels = np.linspace(-6,6,endpoint=True, num=7) + max_channel
    saved_channels = np.intersect1d(near_channels, np.arange(384)).astype(np.int16)
    saved_waveform.append(waveform[:, saved_channels, :])
import json
file = bc_path / 'bombcell_results.json'
with open(file, 'r', encoding='utf-8') as f:
    data = json.load(f)
bc_unittype = data['unitType']
from utils.nwb_bombcell_helper import (
    add_bombcell_columns_to_nwb,
    get_bombcell_metrics_for_unit
)

with NWBHDF5IO(nwbfile_path, 'r+') as io:
    nwbfile = io.read()
    # 添加基本列
    customed_unit_cols = {
        "ks_id" : "kilosort id",
        "unitpos" : "unit position calculated via center of mass",
        "unittype" : "unit type by bombcell, 1=good, 2=mua, 3=non-soma",
        "unittype_string" : "unit type string from bombcell",
        "Raster" : "unit spike raster binned on time window of (pre_onset, post_onset)"
    }
    for metric_name, metric_description in customed_unit_cols.items():
        nwbfile.add_unit_column(
                    name=metric_name,
                    description=metric_description,
                    data=[]  # 将在添加unit时填充
                )
    
    # 添加所有 Bombcell 质量指标列
    add_bombcell_columns_to_nwb(nwbfile, bc_qm_df) 
    # 设置时间窗
    pre_onset = 50 / 1000
    post_onset = 300 / 1000
    baseline_window = [-25 / 1000, 25 / 1000]
    highline_window = [60 / 1000, 220 / 1000]
    # 添加units
    for i_unit in tqdm(range(n_units), total=n_units, desc="Adding units:"):
        epoch_raster = []
        baseline_spikes = []
        highline_spikes = []
        unit_spike_times = spike_times_list[i_unit]
        # 2. 遍历每一个trial
        for index, trial in trial_df.iterrows():
            if trial['fix_success']:
                event_time = trial['start_time']
                
                # 3. 定义当前trial的epoch时间窗口
                epoch_start = event_time - pre_onset
                epoch_end = event_time + post_onset
                
                # 4. 筛选出落在这个时间窗口内的所有放电
                #    使用np.where比直接用布尔索引更快
                indices = np.where((unit_spike_times >= epoch_start) & (unit_spike_times <= epoch_end))[0]
                spikes_in_epoch = unit_spike_times[indices]

                # 5. (核心步骤) 标准化放电时间：减去事件时间，使 t=0 对应事件发生时刻
                aligned_spikes = spikes_in_epoch - event_time

                baseline_indices = np.where((aligned_spikes >= baseline_window[0]) 
                                & (aligned_spikes < baseline_window[1]))[0]
                baseline_spikes.append(len(aligned_spikes[baseline_indices]))

                highline_indices = np.where((aligned_spikes >= highline_window[0]) 
                                & (aligned_spikes < highline_window[1]))[0]
                highline_spikes.append(len(aligned_spikes[highline_indices]))

                # 6. 计算每个bin中的放电次数
                bin_size_s = 0.001
                bins = np.arange(-pre_onset, post_onset + bin_size_s, bin_size_s)
                raster, _ = np.histogram(aligned_spikes, bins=bins)
                epoch_raster.append(raster)
        epoch_raster = np.array(epoch_raster).astype(np.uint8)
        # light modulation
        from scipy.stats import mannwhitneyu
        _, p = mannwhitneyu(baseline_spikes, highline_spikes, 
                            alternative='less',  # 'two-sided', 'less', 'greater'
                            method='auto') 
        # 
        if (p < 0.001) and (bc_unittype[i_unit] != 0):
            unitpos = spike_pos[np.where(spike_template==i_unit)[0],:].mean(axis=0)
            unit_kwargs = {
                'spike_times': unit_spike_times,
                'ks_id' : int(i_unit),
                'unitpos': unitpos,
                'unittype': int(bc_unittype[i_unit]),
                'unittype_string': str(bc_unittype_string[i_unit]),
                'waveforms': saved_waveform[i_unit],
                'Raster' : epoch_raster
            }
            
            # 添加所有 Bombcell 质量指标
            bc_metrics = get_bombcell_metrics_for_unit(bc_qm_df, i_unit)
            unit_kwargs.update(bc_metrics)
            
            nwbfile.add_unit(**unit_kwargs)
    # write nwbfile
    io.write(nwbfile)

