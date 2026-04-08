clear
root_dir = 'F:\NSD_Formal_Folder';
raw_data_dir = fullfile(root_dir,'Data\Raw\SesFolder');
cd(root_dir)
addpath(genpath('C:\Users\admin\AppData\Roaming\MathWorks\MATLAB Add-Ons\Apps\NIMHMonkeyLogic22'))
addpath(genpath(root_dir))
cd(raw_data_dir)
all_dir = dir('2*');
for dir_idx = 1:length(all_dir)
    interested_path{dir_idx} = fullfile(raw_data_dir,all_dir(dir_idx).name);
end


for path_now = 56:59
    wm_dir = fullfile(interested_path{path_now},'processed','BC','RawWaveforms');
    rmdir(wm_dir,'s')
end