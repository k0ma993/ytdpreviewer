using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using SharpShell.Attributes;
using SharpShell.Helpers;
using SharpShell.SharpThumbnailHandler;

namespace YtdThumbnail;

/// <summary>Explorer thumbnail handler for .ydd (flat diffuse texture preview).</summary>
[ComVisible(true)]
[Guid("4c8e1f2a-6b3d-4e59-9c01-2f7e6d5a4b3c")]
[COMServerAssociation(AssociationType.ClassOfExtension, ".ydd")]
public sealed class YddSharpHandler : SharpThumbnailHandler
{
    protected override Bitmap GetThumbnailImage(uint width)
    {
        TempStreamFiles.OnThumbnailStarting();

        var side = (int)Math.Max(32, width);
        var sourcePath = TryGetSourcePath();
        var lookupPath = sourcePath;
        ThumbnailRender.Log($"YddSharp side={side} source={(sourcePath ?? "(stream)")}");

        if (!string.IsNullOrEmpty(sourcePath))
        {
            try
            {
                var direct = ThumbnailRender.RenderToBitmap(sourcePath, side);
                if (direct != null)
                {
                    YddPathResolver.RememberRealPath(sourcePath);
                    TryDeleteShellScratchYdd(sourcePath);
                    if (sourcePath.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) < 0)
                        ThumbnailBackgroundWarm.Schedule(sourcePath, side);
                    return ThumbnailRender.FitSquare(direct, side);
                }
            }
            catch (Exception ex)
            {
                ThumbnailRender.Log("YddSharp direct EX " + ex.Message);
            }
        }

        var temp = Path.Combine(Path.GetTempPath(), "yddprev_" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var file = File.Create(temp))
            {
                SelectedItemStream.Position = 0;
                SelectedItemStream.CopyTo(file);
            }

            if (string.IsNullOrEmpty(lookupPath))
                lookupPath = YddPathResolver.TryResolveRealPath(temp);

            var bmp = ThumbnailRender.RenderToBitmap(temp, side, lookupPath);
            if (bmp != null)
            {
                TempStreamFiles.Retain(temp);
                if (!string.IsNullOrEmpty(lookupPath)
                    && lookupPath.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) < 0
                    && lookupPath.IndexOf("yddprev_", StringComparison.OrdinalIgnoreCase) < 0)
                {
                    YddPathResolver.RememberRealPath(lookupPath);
                    ThumbnailBackgroundWarm.Schedule(lookupPath, side);
                }
                return ThumbnailRender.FitSquare(bmp, side);
            }
        }
        catch (Exception ex)
        {
            ThumbnailRender.Log("YddSharp EX " + ex.Message);
        }

        return ThumbnailRender.FallbackBitmap("ydd.ico", side) ?? new Bitmap(side, side);
    }

    private string? TryGetSourcePath()
    {
        try
        {
            if (SelectedItemStream is ComStream stream && !string.IsNullOrWhiteSpace(stream.Name))
            {
                var name = stream.Name.Trim().Trim('"');
                if (Path.IsPathRooted(name) && File.Exists(name))
                    return name;
            }
        }
        catch
        {
            // ignore
        }

        return null;
    }

    private static void TryDeleteShellScratchYdd(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;
        if (path.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) < 0)
            return;
        if (!path.EndsWith(".ydd", StringComparison.OrdinalIgnoreCase))
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
