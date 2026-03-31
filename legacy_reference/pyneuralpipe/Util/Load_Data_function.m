function Load_Data_function(data_path)
cd(data_path)
clear
mkdir processed
%% Load Data
% Load NI Data
SGLX_Folder = dir('NPX*');
session_name = SGLX_Folder(1).name;
g_number = session_name(end);
NIFileName=fullfile(session_name, sprintf('%s_t0.nidq', session_name));
[NI_META, AIN, DCode_NI] = load_NI_data(NIFileName);

% Load ML Data
ML_FILE = dir('*bhv2');
ml_name = ML_FILE(1).name;
[exp_day, exp_subject] = parsing_ML_name(ml_name);

trial_ML_name = fullfile('processed',sprintf('ML_%s.mat',ml_name(1:end-5)));
file_exist = length(dir(trial_ML_name));
if(file_exist)
    load(trial_ML_name);
else
    trial_ML = mlread(ml_name);
    save(trial_ML_name, "trial_ML")
end


ImecFileName=fullfile(session_name,sprintf('%s_imec0',session_name), sprintf('%s_t0.imec0.lf',session_name));
[IMEC_META, DCode_IMEC] = load_IMEC_data(ImecFileName);
ImecFileName=fullfile(session_name,sprintf('%s_imec0',session_name), sprintf('%s_t0.imec0.ap',session_name));
IMEC_AP_META = load_meta(sprintf('%s.meta', ImecFileName));


figure;
set(gcf,'Position',[100 80 1800 950])
% Do Sync between Devices
SyncLine = examine_and_fix_sync(DCode_NI, DCode_IMEC);


%% check for alignment between ML and NI


onset_times = 0;
offset_times = 0;
onset_times_by_trial_ML = zeros([1, length(trial_ML)]);
for tt = 1:length(trial_ML)
    onset_times_by_trial_ML(tt) = sum(trial_ML(tt).BehavioralCodes.CodeNumbers==64);
    onset_times = onset_times + onset_times_by_trial_ML(tt);
    offset_times = offset_times + sum(trial_ML(tt).BehavioralCodes.CodeNumbers==32);
end
fprintf('MonkeyLogic Has\n%d trials \n%d onset \n%d offset \n', length(trial_ML), onset_times, offset_times)


LOCS = find(diff(bitand(DCode_NI.CodeVal,2))>0)+1;
onset_times_by_trial_SGLX = zeros([1, length(LOCS)]);
for tt = 1:length(LOCS)
    LOC1=LOCS(tt);
    if(tt==length(LOCS))
        LOC2=length(DCode_NI.CodeLoc);
    else
        LOC2=LOCS(tt+1);
    end
    all_code_this_trial = DCode_NI.CodeVal(LOC1:LOC2);
    onset_times_by_trial_SGLX(tt) = length(find(diff(bitand(all_code_this_trial,64))>0));
end


subplot(3,6,1)
scatter(onset_times_by_trial_SGLX,onset_times_by_trial_ML)
xlabel('onset times SGLX'); ylabel('onset times ML')
if(max(onset_times_by_trial_ML-onset_times_by_trial_SGLX)>0)
    warning('Inconsistant Trial Number')
end
title(sprintf('MaxErr=%d',max(onset_times_by_trial_ML-onset_times_by_trial_SGLX)))

%% check for dataset
dataset_pool = {};
for trial_idx = 1:length(trial_ML)
    dataset_pool{trial_idx}=trial_ML(trial_idx).UserVars.DatasetName;
end
dataset_pool = unique(dataset_pool);
dataset_pool = dataset_pool{1};
[kk] = find(dataset_pool=='\');
% get tsv name
img_set_name = dataset_pool(kk(end)+1:end-4);
%% check for eye
eye_thres = 0.999;
valid_eye = 0;
onset_marker = 0;
trial_valid_idx = zeros([1,onset_times]);
dataset_valid_idx = zeros([1,onset_times]);

eye_matrix = [];
for trial_idx = 1:length(trial_ML)
    trial_data = trial_ML(trial_idx);
    onset_duration = trial_data.VariableChanges.onset_time;
    beh_code = trial_data.BehavioralCodes.CodeNumbers;
    beh_time = trial_data.BehavioralCodes.CodeTimes;
    onset_beh_location = find(beh_code==64);
    onset_times_this_trial = length(onset_beh_location);
    img_idx_now = trial_data.UserVars.Current_Image_Train(1:onset_times_this_trial);
    dataset_idx = find(strcmp(trial_ML(trial_idx).UserVars.DatasetName, dataset_pool));
    for onset_idx = 1:onset_times_this_trial
        onset_marker = onset_marker + 1;
        onset_start_to_end = (beh_time(onset_beh_location(onset_idx)):beh_time(onset_beh_location(onset_idx))+onset_duration)./trial_data.AnalogData.SampleInterval;
        onset_start_to_end = floor(onset_start_to_end);   
        try
            eye_data = trial_data.AnalogData.Eye(onset_start_to_end,:);
            if(isempty(eye_matrix))
                eye_matrix = zeros([2,onset_times,length(onset_start_to_end)]);
            end
            for ee = 1:2
                eye_matrix(ee,onset_marker,:) = eye_data(:,ee);
            end
            eye_dist = sqrt(eye_data(:,1).^2+eye_data(:,2).^2);
            eye_ratio = sum(eye_dist<trial_data.VariableChanges.fixation_window)./(onset_duration+1);
            
            if(eye_ratio>eye_thres)
                valid_eye = valid_eye + 1;
                trial_valid_idx(onset_marker) = img_idx_now(onset_idx);
                dataset_valid_idx(onset_marker) = dataset_idx;
            end
        end
    end
end

binx = -8:0.5:8;
biny = -8:0.5:8;
density_plot = zeros([length(binx)-1, length(biny)-1]);
plot_eye = squeeze(mean(eye_matrix,3));
x = plot_eye(1,:);
y = plot_eye(2,:);
for xx = 1:length(binx)-1
    for yy = 1:length(biny)-1
        units_within = find(x>binx(xx) & x<=binx(xx+1) & y>biny(yy) & y<=biny(yy+1));
        density_plot(xx,yy) = length(units_within);
    end
end
subplot(3,6,12)
imagesc(binx-0.15,biny-0.15,log10(density_plot))
xlabel('Eyex')
ylabel('Eyey')

%% Look Up For Real Onset Time  
before_onset_measure = 10;
after_onset_measure = 50;
after_onset_stats = 100;
onset_LOC = find(diff(bitand(DCode_NI.CodeVal,64))>0)+1;
onset_times = length(onset_LOC);
po_dis = zeros([onset_times, 1+before_onset_measure+after_onset_stats]);
onset_time_ms = zeros([1, onset_times]);
for tt = 1:onset_times
    onset_time_ms(tt) = floor(DCode_NI.CodeTime(onset_LOC(tt)));
    start_get_time = onset_time_ms(tt)-before_onset_measure;
    end_get_time = onset_time_ms(tt)+after_onset_stats;
    po_dis(tt,:) = zscore(AIN(start_get_time:end_get_time));
end

subplot(3,6,2)
imagesc(-before_onset_measure:after_onset_stats, 1:onset_times,po_dis)
xlabel('Time ms')
ylabel('Trial')
title('Original Signal')


diff_abs_data = abs(diff(po_dis'));
diff_data = diff(po_dis');

subplot(3,6,3)
imagesc(-before_onset_measure:after_onset_stats, 1:onset_times,diff_data');
xlabel('Time ms')
ylabel('Trial')
title('Diff Signal')

subplot(3,6,4)
imagesc(-before_onset_measure:after_onset_stats, 1:onset_times,diff_abs_data');
xlabel('Time ms')
ylabel('Trial')
title('Diff Abs Signal')

val_array = [];
time_array = [];
sign_array = [];
for tt = 1:size(diff_abs_data,2)
    [val_array(tt),time_array(tt)] = max(diff_abs_data(:,tt));
    if(diff_data(time_array(tt),tt)<0)
        po_dis(tt,:) = -po_dis(tt,:);
        sign_array(tt)=-1;
    else
        sign_array(tt)=1;
    end
end

subplot(3,6,5)
imagesc(po_dis)
xlabel('Time ms')
ylabel('Trial')
title('New Signal')


baseline = mean(mean(po_dis(:,1:before_onset_measure)));
hignline = mean(mean(po_dis(:,before_onset_measure+after_onset_measure+[1:20])));
thres = 0.1*baseline + 0.9*hignline;

subplot(3,6,7)
shadedErrorBar((1:size(po_dis,2))-before_onset_measure,mean(po_dis),std(po_dis))
yline(thres)
xlabel('time from event');title('Before time calibration')

onset_latency = zeros([1, size(po_dis,1)]);
for tt = 1:size(po_dis,1)
    onset_latency(tt) = find(po_dis(tt,:)>thres,1)-before_onset_measure;
    onset_time_ms(tt) = onset_time_ms(tt) + onset_latency(tt);
end
subplot(3,6,10); hist(onset_latency,20);
xlabel('Latency ms')
xline(min(onset_latency),'LineWidth',2); xline(max(onset_latency),'LineWidth',2)

subplot(3,6,8)
po_dis = zeros([onset_times, 1+before_onset_measure+after_onset_stats]);
for tt = 1:onset_times
    po_dis(tt,:) = AIN(onset_time_ms(tt)-before_onset_measure:onset_time_ms(tt)+after_onset_stats);
    po_dis(tt,:) = zscore(po_dis(tt,:));
    po_dis(tt,:) = po_dis(tt,:).*sign_array(tt);
end
shadedErrorBar((1:size(po_dis,2))-before_onset_measure,mean(po_dis),std(po_dis))
xlabel('time from event'); title('After time calibration')

subplot(3,6,9)
po_dis = zeros([onset_times, 1+before_onset_measure+after_onset_stats]);
for tt = 1:onset_times
    if(dataset_valid_idx(tt))
        po_dis(tt,:) = AIN(onset_time_ms(tt)-before_onset_measure:onset_time_ms(tt)+after_onset_stats);
        po_dis(tt,:) = zscore(po_dis(tt,:));
        po_dis(tt,:) = po_dis(tt,:).*sign_array(tt);
    end
end

po_dis(~dataset_valid_idx,:)=[];
shadedErrorBar((1:size(po_dis,2))-before_onset_measure,mean(po_dis),std(po_dis))
xlabel('time from event'); title('Exclude Non-Look Trial')
sgtitle(pwd)


dataset_idx = 1;
subplot(3,6,11)
img_idx = dataset_valid_idx==dataset_idx;
valid_onset = trial_valid_idx(img_idx);
onset_t = [];
img_size = max(valid_onset);
for img = 1:img_size
    onset_t(img) = sum(valid_onset==img);
end
plot(1:img_size,onset_t)
xlim([1,img_size])
ylim([0, max(onset_t)+1])
xlabel('Stimuli Idx')
ylabel('Number of trials')

saveas(gcf,'processed\DataCheck')
saveas(gcf,'processed\DataCheck.png')
save_name = fullfile('processed',sprintf('META_%s_%s_%s.mat', exp_day, exp_subject, img_set_name));
onset_time_ms = onset_time_ms-5 ; % fix monitor time err in 60Hz

save(save_name, "eye_matrix","ml_name","trial_valid_idx", "dataset_valid_idx", "onset_time_ms", "NI_META", "AIN", "DCode_NI", "IMEC_META","DCode_IMEC","SyncLine","IMEC_AP_META","img_size","g_number","exp_subject",'exp_day');
end