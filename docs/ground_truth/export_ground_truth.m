function export_bhv2_ground_truth(bhv2_file, output_dir)
% Export BHV2 file contents to JSON ground truth fixtures for Python testing.
%
% Usage:
%   addpath('F:\tools\pynpxpipe\legacy_reference\pyneuralpipe\Util');
%   addpath('F:\tools\pynpxpipe\docs\ground_truth');
%   export_bhv2_ground_truth( ...
%       'F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2', ...
%       'F:\tools\pynpxpipe\tests\fixtures\bhv2_ground_truth');

if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end

fprintf('Opening: %s\n', bhv2_file);
reader = mlbhv2(bhv2_file, 'r');

% --- enumerate all variables ---
var_names = reader.who();
fprintf('Variables found (%d): %s\n', numel(var_names), strjoin(var_names, ', '));

trial_names = var_names(~cellfun(@isempty, regexp(var_names, '^Trial\d+$', 'once')));
known_names = {'MLConfig', 'FileInfo', 'FileIndex'};
extra_names = setdiff(var_names, [trial_names(:)', known_names]);

% sort trials by number
trial_nums = cellfun(@(n) str2double(regexp(n, '\d+', 'match', 'once')), trial_names);
[~, idx]   = sort(trial_nums);
trial_names = trial_names(idx);

% --- export trials ---
for i = 1:numel(trial_names)
    name = trial_names{i};
    num  = str2double(regexp(name, '\d+', 'match', 'once'));
    fprintf('  Exporting %s ...\n', name);
    try
        val  = reader.read(name);
        json = safe_encode(val);
        write_json(json, fullfile(output_dir, sprintf('trial_%02d.json', num)));
    catch err
        fprintf('  ERROR in %s: %s\n', name, err.message);
    end
end

% --- export known session-level variables ---
name_to_file = struct('MLConfig','ml_config.json', ...
                      'FileInfo','file_info.json', ...
                      'FileIndex','file_index.json');
fields = fieldnames(name_to_file);
for i = 1:numel(fields)
    name = fields{i};
    fprintf('  Exporting %s ...\n', name);
    try
        val  = reader.read(name);
        json = safe_encode(val);
        write_json(json, fullfile(output_dir, name_to_file.(name)));
    catch err
        fprintf('  ERROR in %s: %s\n', name, err.message);
    end
end

% --- write index.json ---
[~, fname, fext] = fileparts(bhv2_file);
index_s = struct();
index_s.source_file        = [fname fext];
index_s.md5                = file_md5(bhv2_file);
index_s.trial_count        = numel(trial_names);
index_s.exported_variables = [trial_names(:)', known_names];
index_s.extra_variables    = extra_names(:)';
index_s.exported_at        = datestr(now, 'yyyy-mm-dd HH:MM:SS');
index_s.matlab_version     = version;
write_json(jsonencode(index_s, 'PrettyPrint', true), ...
           fullfile(output_dir, 'index.json'));

reader.close();
fprintf('Done. Output: %s\n', output_dir);
end


% =========================================================================
function json = safe_encode(val)
% Serialize MATLAB value to pretty-printed JSON string.
    cleaned = clean(val);
    json    = jsonencode(cleaned, 'PrettyPrint', true);
end


function out = clean(val)
% Recursively convert MATLAB value to JSON-serializable form.
    if isa(val, 'function_handle')
        out = struct('tp', 'fh', 'v', func2str(val));

    elseif isa(val, 'containers.Map')
        try
            k   = keys(val);
            v   = cellfun(@clean, values(val), 'UniformOutput', false);
            out = struct('tp', 'map', 'keys', {k}, 'values', {v});
        catch
            out = struct('tp', 'unsupported', 'class', 'containers.Map');
        end

    elseif isstruct(val)
        fns = fieldnames(val);
        out = repmat(struct(), size(val));
        for i = 1:numel(val)
            for j = 1:numel(fns)
                out(i).(fns{j}) = clean(val(i).(fns{j}));
            end
        end

    elseif iscell(val)
        out = cellfun(@clean, val, 'UniformOutput', false);

    elseif isnumeric(val) && ~isscalar(val)
        % Store as {_t, dt, sh, d} — d is Fortran-order flat (column-major)
        dt_map = struct('double','float64','single','float32', ...
                        'uint8','uint8','uint16','uint16', ...
                        'uint32','uint32','uint64','uint64', ...
                        'int8','int8','int16','int16', ...
                        'int32','int32','int64','int64');
        cn = class(val);
        if isfield(dt_map, cn), dtype = dt_map.(cn); else, dtype = cn; end
        % val(:) flattens column-major; cast to double for JSON numbers
        out = struct('tp','nd', 'dt',dtype, 'sh',{size(val)}, 'd',{double(val(:))'});

    elseif isnumeric(val) && isscalar(val)
        if isnan(val),          out = '__NaN__';
        elseif isinf(val) && val > 0, out = '__Inf__';
        elseif isinf(val),      out = '__-Inf__';
        else,                   out = val;
        end

    elseif islogical(val)
        out = val;

    elseif ischar(val)
        out = val;

    else
        out = struct('tp', 'unsupported', 'class', class(val));
    end
end


function write_json(json_str, filepath)
    fid = fopen(filepath, 'w', 'n', 'UTF-8');
    if fid == -1
        error('Cannot open file for writing: %s', filepath);
    end
    fwrite(fid, json_str, 'char');
    fclose(fid);
end


function md5 = file_md5(filepath)
    try
        import java.security.MessageDigest
        import java.io.File
        import java.io.FileInputStream
        fis    = FileInputStream(File(filepath));
        digest = MessageDigest.getInstance('MD5');
        buf    = zeros(1, 65536, 'int8');
        n      = fis.read(buf);
        while n > 0
            digest.update(buf, 0, n);
            n = fis.read(buf);
        end
        fis.close();
        bytes = typecast(digest.digest(), 'uint8');
        md5   = sprintf('%02x', bytes);
    catch
        md5 = 'unavailable';
    end
end
