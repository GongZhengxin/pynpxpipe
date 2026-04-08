clear
close all
root_dir = pwd;
cd(root_dir)
addpath(genpath('C:\Users\admin\AppData\Roaming\MathWorks\MATLAB Add-Ons\Apps\NIMHMonkeyLogic22'))
addpath(genpath(root_dir))


interested_path{1}='...';

for path_now = 1:23
    Load_Data_function(interested_path{path_now});
    PostProcess_function_raw(interested_path{path_now});
    PostProcess_function(interested_path{path_now});
end