function fp = mlfileopen(filepath,mode)

if ~exist('mode','var'), mode = 'r'; end

[~,~,e] = fileparts(filepath);
switch lower(e)
    case '.bhvz', fp = mlbhvz(filepath,mode);
    case '.bhv2', fp = mlbhv2(filepath,mode);
    case '.h5', fp = mlhdf5(filepath,mode);
    case '.mat', fp = mlmat(filepath,mode);
    otherwise, error('Unknown file format');
end

end
