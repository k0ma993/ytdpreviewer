using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;

namespace YtdThumbnail;

internal static class ThumbnailRender
{
    internal const int MaxThumbnailSide = 1024;

    internal static string InstallDir()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var preferred = Path.Combine(local, "YTDPreviewer");
        if (Directory.Exists(preferred))
            return preferred;

        var fromDll = Path.GetDirectoryName(typeof(ThumbnailRender).Assembly.Location) ?? "";
        return string.IsNullOrEmpty(fromDll) ? preferred : fromDll;
    }

    internal static Bitmap FitSquare(Bitmap source, int side)
    {
        var target = Math.Max(32, side);
        if (source.Width == target && source.Height == target)
            return source;

        var scaled = new Bitmap(target, target);
        using (var g = Graphics.FromImage(scaled))
        {
            g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
            g.DrawImage(source, 0, 0, target, target);
        }
        source.Dispose();
        return scaled;
    }

    internal static Bitmap? FallbackBitmap(string iconFileName, int side)
    {
        var target = Math.Max(32, Math.Min(side, MaxThumbnailSide));
        var installDir = InstallDir();
        var candidates = new[]
        {
            Path.Combine(installDir, "assets", iconFileName),
            Path.Combine(Path.GetDirectoryName(typeof(ThumbnailRender).Assembly.Location) ?? "", "assets", iconFileName),
        };

        foreach (var path in candidates)
        {
            if (!File.Exists(path))
                continue;
            try
            {
                using var icon = new Icon(path);
                using var raw = icon.ToBitmap();
                if (raw.Width == target && raw.Height == target)
                    return new Bitmap(raw);
                var scaled = new Bitmap(target, target);
                using (var g = Graphics.FromImage(scaled))
                {
                    g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                    g.DrawImage(raw, 0, 0, target, target);
                }
                return scaled;
            }
            catch
            {
                // try next path
            }
        }

        return null;
    }

    internal static void Log(string message)
    {
        try
        {
            var dir = InstallDir();
            Directory.CreateDirectory(dir);
            File.AppendAllText(
                Path.Combine(dir, "thumb.log"),
                $"{DateTime.Now:O} {message}{Environment.NewLine}");
        }
        catch
        {
            // ignore
        }
    }

    internal static bool WarmToCache(string ytdPath, int size)
    {
        _ = size;
        if (ThumbnailCache.TryGetCachedPng(ytdPath, MaxThumbnailSide) != null)
            return true;

        using var bmp = RenderToBitmap(ytdPath, MaxThumbnailSide);
        return bmp != null;
    }

    internal static bool IsYddAssetPath(string assetPath)
    {
        var ext = Path.GetExtension(assetPath);
        if (ext.Equals(".ydd", StringComparison.OrdinalIgnoreCase))
            return true;
        var name = Path.GetFileName(assetPath) ?? "";
        // ytd stream copies use ytdprev_*.tmp; ydd uses yddprev_*.tmp (do not mix).
        return name.StartsWith("yddprev_", StringComparison.OrdinalIgnoreCase)
            && ext.Equals(".tmp", StringComparison.OrdinalIgnoreCase);
    }

    internal static Bitmap? RenderToBitmap(string assetPath, int size, string? textureLookupPath = null)
    {
        if (IsYddAssetPath(assetPath))
            return RenderYddToBitmap(assetPath, size, textureLookupPath);
        return RenderYtdToBitmap(assetPath, size);
    }

    private static Bitmap? RenderYtdToBitmap(string ytdPath, int size)
    {
        var requested = Math.Max(32, Math.Min(size, MaxThumbnailSide));
        var fast = requested <= 384;
        var renderSide = fast ? requested : MaxThumbnailSide;
        var cached = ThumbnailCache.TryGetCachedPng(ytdPath, requested);
        var scheduleWarm = ytdPath.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) < 0;

        if (cached != null)
        {
            var hit = LoadBitmapFull(cached);
            if (hit != null)
            {
                if (scheduleWarm)
                    ThumbnailBackgroundWarm.Schedule(ytdPath, requested);
                return hit;
            }
        }

        var installDir = InstallDir();
        var temp = Path.Combine(Path.GetTempPath(), "ytdprev_" + Guid.NewGuid().ToString("N") + ".png");
        var px = renderSide.ToString();
        var fastArg = fast ? " --fast" : "";
        var timeoutMs = fast ? 20000 : 45000;

        try
        {
            if (TryRenderViaExe(installDir, ytdPath, temp, px, $"--thumbnail \"{ytdPath}\" \"{temp}\" {px}{fastArg}", timeoutMs, out var via)
                || TryRenderViaPyw(installDir, ytdPath, temp, px, fast, timeoutMs, out via)
                || TryRenderViaCmd(installDir, ytdPath, temp, px, timeoutMs, out via))
            {
                var bmp = FinishRender(ytdPath, temp, requested, via);
                if (bmp != null && scheduleWarm)
                    ThumbnailBackgroundWarm.Schedule(ytdPath, requested);
                return bmp;
            }

            return null;
        }
        finally
        {
            TryDelete(temp);
        }
    }

    private static Bitmap? RenderYddToBitmap(string yddPath, int size, string? textureLookupPath = null)
    {
        var requested = Math.Max(32, Math.Min(size, MaxThumbnailSide));
        var renderSide = Math.Max(128, Math.Min(requested, 256));
        var cacheKeyPath = ResolveYddCacheKeyPath(yddPath, textureLookupPath);
        var cached = ThumbnailCache.TryGetCachedPng(cacheKeyPath, requested, "flat")
            ?? ThumbnailCache.TryGetCachedPng(cacheKeyPath, requested);
        var scheduleWarm = IsRealAssetPath(cacheKeyPath);

        if (cached != null)
        {
            var hit = LoadBitmapFull(cached);
            if (hit != null)
                return hit;
        }

        var installDir = InstallDir();
        var temp = Path.Combine(Path.GetTempPath(), "ytdprev_" + Guid.NewGuid().ToString("N") + ".png");
        var px = renderSide.ToString();
        const int flatTimeoutMs = 20000;

        try
        {
            var yddCli = $"--ydd-thumbnail \"{yddPath}\" \"{temp}\" {px}";
            if (TryRenderViaExe(installDir, yddPath, temp, px, yddCli, flatTimeoutMs, out var via)
                || TryRenderViaPywYdd(installDir, yddPath, temp, px, flatTimeoutMs, textureLookupPath, out via)
                || TryRenderViaCmd(installDir, yddPath, temp, px, flatTimeoutMs, out via))
            {
                var bmp = FinishRender(cacheKeyPath, temp, requested, via);
                if (bmp != null && scheduleWarm)
                    ThumbnailBackgroundWarm.Schedule(cacheKeyPath, requested);
                return bmp;
            }

            Log("YDD thumbnail render failed " + yddPath);
            return null;
        }
        finally
        {
            TryDelete(temp);
        }
    }

    private static bool IsRealAssetPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return false;
        if (path.IndexOf("ytdprev_", StringComparison.OrdinalIgnoreCase) >= 0)
            return false;
        if (path.IndexOf("yddprev_", StringComparison.OrdinalIgnoreCase) >= 0)
            return false;
        return true;
    }

    private static string ResolveYddCacheKeyPath(string yddPath, string? textureLookupPath)
    {
        if (!string.IsNullOrWhiteSpace(textureLookupPath)
            && File.Exists(textureLookupPath)
            && textureLookupPath.EndsWith(".ydd", StringComparison.OrdinalIgnoreCase))
            return textureLookupPath;
        return yddPath;
    }

    private static bool RenderOutputOk(string tempPng)
    {
        try
        {
            return File.Exists(tempPng) && new FileInfo(tempPng).Length > 512;
        }
        catch
        {
            return false;
        }
    }

    private static bool TryRenderViaExe(
        string installDir,
        string src,
        string temp,
        string px,
        string cliArgs,
        int timeoutMs,
        out string via)
    {
        via = "exe";
        var exe = Path.Combine(installDir, "YTDPreviewer.exe");
        return File.Exists(exe)
            && RunProcess(exe, cliArgs, timeoutMs, installDir, out _)
            && RenderOutputOk(temp);
    }

    private static bool TryRenderViaPyw(
        string installDir,
        string ytdPath,
        string temp,
        string px,
        bool fast,
        int timeoutMs,
        out string via)
    {
        via = "pyw";
        var pyw = Path.Combine(installDir, "thumbnail.pyw");
        if (!File.Exists(pyw))
            return false;

        var pywArgs = fast
            ? $"\"{pyw}\" \"{ytdPath}\" \"{temp}\" {px} ytd fast"
            : $"\"{pyw}\" \"{ytdPath}\" \"{temp}\" {px} ytd";
        foreach (var pythonw in FindPythonwCandidates(installDir))
        {
            if (RunProcess(pythonw, pywArgs, timeoutMs, installDir, out _)
                && RenderOutputOk(temp))
                return true;
        }
        return false;
    }

    private static bool TryRenderViaPywYdd(
        string installDir,
        string yddPath,
        string temp,
        string px,
        int timeoutMs,
        string? textureLookupPath,
        out string via)
    {
        via = "pyw-ydd";
        var pyw = Path.Combine(installDir, "thumbnail.pyw");
        if (!File.Exists(pyw))
            return false;

        const string modeArg = "ydd flat";
        var lookupArg = "";
        if (!string.IsNullOrWhiteSpace(textureLookupPath)
            && File.Exists(textureLookupPath)
            && !string.Equals(textureLookupPath, yddPath, StringComparison.OrdinalIgnoreCase))
            lookupArg = $" \"{textureLookupPath}\"";
        var pywArgs = $"\"{pyw}\" \"{yddPath}\" \"{temp}\" {px} {modeArg}{lookupArg}";
        foreach (var pythonw in FindPythonwCandidates(installDir))
        {
            if (RunProcess(pythonw, pywArgs, timeoutMs, installDir, out _)
                && RenderOutputOk(temp))
                return true;
        }
        return false;
    }

    private static bool TryRenderViaCmd(
        string installDir,
        string src,
        string temp,
        string px,
        int timeoutMs,
        out string via)
    {
        via = "cmd";
        var cmd = Path.Combine(installDir, "thumbnail.cmd");
        if (!File.Exists(cmd))
            return false;

        var args = $"/c \"\"{cmd}\" \"{src}\" \"{temp}\" {px}\"";
        if (RunProcess("cmd.exe", args, timeoutMs, installDir, out var cmdExit)
            && RenderOutputOk(temp))
            return true;
        Log($"thumbnail.cmd failed exit={cmdExit}");
        return false;
    }

    private static void TryDelete(string path)
    {
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

    private static Bitmap? FinishRender(
        string ytdPath, string tempPng, int requestedSize, string via, string cacheMode = "")
    {
        if (!File.Exists(tempPng) || new FileInfo(tempPng).Length <= 512)
            return null;
        ThumbnailCache.StorePng(ytdPath, MaxThumbnailSide, tempPng, cacheMode);
        var bmp = LoadBitmapFull(tempPng);
        if (bmp == null)
            return null;

        var deliver = Math.Max(Math.Max(requestedSize, 128), 96);
        if (bmp.Width < deliver || bmp.Height < deliver)
            bmp = FitSquare(bmp, deliver);

        Log($"OK via={via} req={requestedSize} out={bmp.Width}x{bmp.Height} {ytdPath}");
        return bmp;
    }

    private static IEnumerable<string> FindPythonwCandidates(string installDir)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var cfg = Path.Combine(installDir, "pythonw.txt");
        if (File.Exists(cfg))
        {
            var line = File.ReadAllText(cfg).Trim();
            if (TryAddCandidate(seen, line, out var fromCfg))
                yield return fromCfg;
        }

        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        foreach (var pattern in new[]
                 {
                     Path.Combine(local, "Programs", "Python", "Python313", "pythonw.exe"),
                     Path.Combine(local, "Programs", "Python", "Python312", "pythonw.exe"),
                     Path.Combine(local, "Programs", "Python", "Python311", "pythonw.exe"),
                 })
        {
            if (TryAddCandidate(seen, pattern, out var full))
                yield return full;
        }
    }

    private static bool TryAddCandidate(HashSet<string> seen, string path, out string full)
    {
        try
        {
            full = Path.GetFullPath(path);
        }
        catch
        {
            full = "";
            return false;
        }
        if (!File.Exists(full) || !seen.Add(full))
        {
            full = "";
            return false;
        }
        var name = Path.GetFileName(full);
        if (name.Equals("setup.exe", StringComparison.OrdinalIgnoreCase)
            || name.Equals("YTDPreviewer.exe", StringComparison.OrdinalIgnoreCase))
        {
            full = "";
            return false;
        }
        return true;
    }

    private static bool RunProcess(
        string fileName,
        string arguments,
        int timeoutMs,
        string? workingDir,
        out int exitCode)
    {
        exitCode = -1;
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            if (!string.IsNullOrEmpty(workingDir))
                psi.WorkingDirectory = workingDir;
            using var proc = Process.Start(psi);
            if (proc == null)
                return false;
            if (!proc.WaitForExit(timeoutMs))
            {
                try { proc.Kill(); } catch { /* ignore */ }
                exitCode = -2;
                return false;
            }
            exitCode = proc.ExitCode;
            return exitCode == 0;
        }
        catch (Exception ex)
        {
            Log("RunProcess EX " + fileName + ": " + ex.Message);
            return false;
        }
    }

    /// <summary>Return PNG at native resolution — do not shrink for small Explorer cx (avoids upscale blur on zoom).</summary>
    private static Bitmap? LoadBitmapFull(string temp)
    {
        if (!File.Exists(temp) || new FileInfo(temp).Length <= 64)
            return null;

        using var loaded = new Bitmap(temp);
        return new Bitmap(loaded);
    }

    private static Bitmap? LoadBitmap(string temp, int size)
    {
        return LoadBitmapFull(temp);
    }

    private static bool NeedsScale(Bitmap bmp, int size)
    {
        var maxSide = Math.Max(32, Math.Min(size, MaxThumbnailSide));
        var ratio = Math.Min((double)maxSide / bmp.Width, (double)maxSide / bmp.Height);
        if (Math.Abs(ratio - 1.0) < 0.03)
            return false;
        var w = Math.Max(1, (int)Math.Round(bmp.Width * ratio));
        var h = Math.Max(1, (int)Math.Round(bmp.Height * ratio));
        return w != bmp.Width || h != bmp.Height;
    }

    internal static Bitmap ScaleBitmapToFit(Bitmap bmp, int size)
    {
        var maxSide = Math.Max(32, Math.Min(size, MaxThumbnailSide));
        var ratio = Math.Min((double)maxSide / bmp.Width, (double)maxSide / bmp.Height);
        var w = Math.Max(1, (int)Math.Round(bmp.Width * ratio));
        var h = Math.Max(1, (int)Math.Round(bmp.Height * ratio));
        if (w == bmp.Width && h == bmp.Height)
            return (Bitmap)bmp.Clone();

        var scaled = new Bitmap(w, h);
        using (var g = Graphics.FromImage(scaled))
        {
            g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;
            g.CompositingQuality = System.Drawing.Drawing2D.CompositingQuality.HighQuality;
            g.DrawImage(bmp, 0, 0, w, h);
        }
        return scaled;
    }
}
