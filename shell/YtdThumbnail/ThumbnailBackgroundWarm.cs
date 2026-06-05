using System;
using System.Collections.Concurrent;
using System.IO;
using System.Threading.Tasks;

namespace YtdThumbnail;

/// <summary>
/// Pre-renders other .ytd files in the same folder in parallel (Explorer requests one file at a time).
/// </summary>
internal static class ThumbnailBackgroundWarm
{
    private static readonly ConcurrentDictionary<string, byte> ActiveDirs =
        new(StringComparer.OrdinalIgnoreCase);

    private const int MaxParallel = 4;
    private const int DefaultWarmSide = 256;

    internal static void Schedule(string? ytdPath, int requestedSize)
    {
        if (string.IsNullOrWhiteSpace(ytdPath))
            return;
        if (ytdPath.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) >= 0
            || ytdPath.IndexOf("yddprev_", StringComparison.OrdinalIgnoreCase) >= 0)
            return;

        if (ytdPath.EndsWith(".ydd", StringComparison.OrdinalIgnoreCase))
            YddPathResolver.RememberRealPath(ytdPath);

        string? dir;
        try
        {
            dir = Path.GetDirectoryName(ytdPath);
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir))
                return;
        }
        catch
        {
            return;
        }

        if (!ActiveDirs.TryAdd(dir, 0))
            return;

        var side = Math.Max(32, Math.Min(requestedSize > 0 ? requestedSize : DefaultWarmSide, 384));
        Task.Run(() => WarmDirectory(dir, side));
    }

    private static void WarmDirectory(string dir, int side)
    {
        try
        {
            string[] ytdFiles;
            try
            {
                ytdFiles = Directory.GetFiles(dir, "*.ytd");
            }
            catch
            {
                return;
            }

            if (ytdFiles.Length == 0)
                return;

            ThumbnailRender.Log($"Warm start {ytdFiles.Length} ytd in {dir}");

            var ytdOptions = new ParallelOptions { MaxDegreeOfParallelism = MaxParallel };
            Parallel.ForEach(
                ytdFiles,
                ytdOptions,
                path =>
                {
                    try
                    {
                        if (ThumbnailCache.TryGetCachedPng(path, side) != null)
                            return;
                        ThumbnailRender.WarmToCache(path, side);
                    }
                    catch (Exception ex)
                    {
                        ThumbnailRender.Log("Warm EX " + path + ": " + ex.Message);
                    }
                });

            ThumbnailRender.Log($"Warm done {dir}");
        }
        finally
        {
            ActiveDirs.TryRemove(dir, out _);
        }
    }
}
