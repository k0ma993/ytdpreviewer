using System;
using System.IO;

namespace YtdThumbnail;

/// <summary>
/// Explorer may pass ytdprev_* temp paths to the open verb; do not delete immediately after thumbnail render.
/// </summary>
internal static class TempStreamFiles
{
    private static string? _stalePath;

    internal static void OnThumbnailStarting()
    {
        TryDelete(_stalePath);
        _stalePath = null;
    }

    internal static void Retain(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;
        var isScratch = path.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) >= 0
            || path.IndexOf("yddprev_", StringComparison.OrdinalIgnoreCase) >= 0;
        if (!isScratch)
            return;
        // Only keep .tmp scratch files — .ydd/.ytd in %TEMP% trigger our file association (open spam).
        if (!path.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase))
            return;

        if (!string.Equals(_stalePath, path, StringComparison.OrdinalIgnoreCase))
            TryDelete(_stalePath);

        _stalePath = path;
    }

    private static void TryDelete(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;
        try
        {
            if (File.Exists(path))
                File.Delete(path);
        }
        catch
        {
            // ignore
        }
    }
}
