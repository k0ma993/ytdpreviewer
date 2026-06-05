using System;
using System.Collections.Generic;
using System.IO;

namespace YtdThumbnail;

/// <summary>
/// Explorer stream thumbnails omit the real .ydd path; resolve via content fingerprint + known asset folders.
/// </summary>
internal static class YddPathResolver
{
    private const int RootScanDepth = 8;
    private const int DriveScanDepth = 14;
    private static readonly TimeSpan DriveScanBudget = TimeSpan.FromSeconds(12);

    private static readonly HashSet<string> SkipDirNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "$recycle.bin",
        ".git",
        "appdata",
        "node_modules",
        "nuget",
        "packages",
        "program files",
        "program files (x86)",
        "system volume information",
        "windows",
    };

    internal static string? TryResolveRealPath(string tempYddPath)
    {
        if (string.IsNullOrWhiteSpace(tempYddPath) || !File.Exists(tempYddPath))
            return null;

        AssetFingerprint fp;
        try
        {
            fp = AssetFingerprint.Describe(tempYddPath);
        }
        catch
        {
            return null;
        }

        var cached = ReadPathCache(fp.Hash8);
        if (!string.IsNullOrEmpty(cached))
            return cached;

        foreach (var root in LoadThumbRoots())
        {
            var hit = ScanTree(root, fp, RootScanDepth, DateTime.UtcNow.AddSeconds(4));
            if (hit != null)
                return RememberAndReturn(hit);
        }

        var driveHit = ScanKnownDrives(fp);
        if (driveHit != null)
            return RememberAndReturn(driveHit);

        ThumbnailRender.Log("YddPathResolver miss len=" + fp.Length);
        return null;
    }

    private static string RememberAndReturn(string realYddPath)
    {
        RememberRealPath(realYddPath);
        ThumbnailRender.Log("YddPathResolver hit " + realYddPath);
        return realYddPath;
    }

    private static string? ScanKnownDrives(AssetFingerprint fp)
    {
        var deadline = DateTime.UtcNow.Add(DriveScanBudget);
        var drives = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var root in LoadThumbRoots())
        {
            var drive = Path.GetPathRoot(root);
            if (!string.IsNullOrWhiteSpace(drive))
                drives.Add(drive);
        }

        foreach (var drive in drives)
        {
            if (DateTime.UtcNow >= deadline)
                break;
            var hit = ScanTree(drive, fp, DriveScanDepth, deadline);
            if (hit != null)
                return hit;
        }

        return null;
    }

    private static string? ScanTree(string startDir, AssetFingerprint fp, int maxDepth, DateTime deadline)
    {
        if (DateTime.UtcNow >= deadline)
            return null;
        if (string.IsNullOrWhiteSpace(startDir) || !Directory.Exists(startDir))
            return null;

        var pending = new Queue<(string Dir, int Depth)>();
        pending.Enqueue((startDir, 0));

        while (pending.Count > 0)
        {
            if (DateTime.UtcNow >= deadline)
                return null;

            var (dir, depth) = pending.Dequeue();
            if (ShouldSkipDir(dir))
                continue;

            try
            {
                foreach (var ydd in Directory.EnumerateFiles(dir, "*.ydd"))
                {
                    if (fp.MatchesFile(ydd))
                        return ydd;
                }

                if (depth >= maxDepth)
                    continue;

                foreach (var sub in Directory.EnumerateDirectories(dir))
                    pending.Enqueue((sub, depth + 1));
            }
            catch
            {
                // ignore unreadable folders
            }
        }

        return null;
    }

    private static bool ShouldSkipDir(string dir)
    {
        var name = Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        return !string.IsNullOrEmpty(name) && SkipDirNames.Contains(name);
    }

    internal static void RememberRealPath(string realYddPath)
    {
        if (string.IsNullOrWhiteSpace(realYddPath) || !File.Exists(realYddPath))
            return;
        if (!realYddPath.EndsWith(".ydd", StringComparison.OrdinalIgnoreCase))
            return;

        try
        {
            var fp = AssetFingerprint.Describe(realYddPath);
            var dir = Path.Combine(ThumbnailRender.InstallDir(), "thumb_paths");
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, fp.Hash8 + ".txt"), realYddPath);
            AppendThumbRoot(Path.GetDirectoryName(realYddPath) ?? "");
        }
        catch
        {
            // ignore
        }
    }

    internal static void AppendThumbRoot(string? folder)
    {
        if (string.IsNullOrWhiteSpace(folder))
            return;
        try
        {
            var full = Path.GetFullPath(folder);
            if (!Directory.Exists(full))
                return;

            var rootsFile = Path.Combine(ThumbnailRender.InstallDir(), "thumb_roots.txt");
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (File.Exists(rootsFile))
            {
                foreach (var line in File.ReadAllLines(rootsFile))
                {
                    var trimmed = line.Trim();
                    if (!string.IsNullOrEmpty(trimmed))
                        seen.Add(trimmed);
                }
            }

            if (!seen.Add(full))
                return;

            var lines = new List<string>(seen);
            lines.Sort(StringComparer.OrdinalIgnoreCase);
            Directory.CreateDirectory(Path.GetDirectoryName(rootsFile) ?? ThumbnailRender.InstallDir());
            File.WriteAllLines(rootsFile, lines);
        }
        catch
        {
            // ignore
        }
    }

    private static string? ReadPathCache(string hash8)
    {
        try
        {
            var path = Path.Combine(ThumbnailRender.InstallDir(), "thumb_paths", hash8 + ".txt");
            if (!File.Exists(path))
                return null;
            var real = File.ReadAllText(path).Trim().Trim('"');
            return File.Exists(real) ? real : null;
        }
        catch
        {
            return null;
        }
    }

    private static IEnumerable<string> LoadThumbRoots()
    {
        var rootsFile = Path.Combine(ThumbnailRender.InstallDir(), "thumb_roots.txt");
        if (!File.Exists(rootsFile))
            yield break;

        foreach (var line in File.ReadAllLines(rootsFile))
        {
            var trimmed = line.Trim().Trim('"');
            if (!string.IsNullOrEmpty(trimmed))
                yield return trimmed;
        }
    }
}
