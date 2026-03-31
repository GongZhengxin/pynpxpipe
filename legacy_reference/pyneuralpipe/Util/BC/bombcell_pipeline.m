currentPath = [fileparts(matlab.desktop.editor.getActiveFilename), filesep, '..'];
ephysKilosortPath = 'C:\Users\MoonLi\Desktop\WrodLOC1\kilosort_def_5block_97';% path to your kilosort output files
ephysRawDir = dir('C:\Users\MoonLi\Desktop\WrodLOC1\NPX_FC2407015_exp_g2\NPX_FC2407015_exp_g2_imec0/*ap*.*bin'); % dir() path to your raw .bin or .dat data. currently NaN because storing raw data on github is cumbersome.
ephysMetaDir = dir("C:\Users\MoonLi\Desktop\WrodLOC1\NPX_FC2407015_exp_g2\NPX_FC2407015_exp_g2_imec0/*ap*meta"); % dir() path to your .meta or .oebin meta file
savePath = 'C:\Users\MoonLi\Desktop\bombcell-main\bombcell-main\saving'; % where you want to save the quality metrics
decompressDataLocal = ''; % where to save raw decompressed ephys data
gain_to_uV = NaN;
kilosortVersion = 4;
%% load data
[spikeTimes_samples, spikeTemplates, templateWaveforms, templateAmplitudes, pcFeatures, ...
    pcFeatureIdx, channelPositions] = bc.load.loadEphysData(ephysKilosortPath);
%% detect whether data is compressed, decompress locally if necessary
rawFile = bc.dcomp.manageDataCompression(ephysRawDir, decompressDataLocal);
%% which quality metric parameters to extract and thresholds
param = bc.qm.qualityParamValues(ephysMetaDir, rawFile, ephysKilosortPath, gain_to_uV, kilosortVersion); %for unitmatch, run this:
param.nChannels = 385;
param.nSyncChannels = 1;
%% compute quality metrics
[qMetric, unitType] = bc.qm.runAllQualityMetrics(param, spikeTimes_samples, spikeTemplates, ...
    templateWaveforms, templateAmplitudes, pcFeatures, pcFeatureIdx, channelPositions, savePath);
