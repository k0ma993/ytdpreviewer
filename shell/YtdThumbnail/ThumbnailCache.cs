using System;

using System.IO;




namespace YtdThumbnail;



internal static class ThumbnailCache

{

    private static readonly int[] LegacyLookupSizes = { 1024, 512, 256, 128, 96, 80, 64, 48, 32 };



    internal static string CacheDir()

    {

        return Path.Combine(ThumbnailRender.InstallDir(), "thumbcache");

    }



    internal static string? TryGetCachedPng(string ytdPath, int requestedSize, string mode = "")

    {

        var need = Math.Max(32, Math.Min(requestedSize, ThumbnailRender.MaxThumbnailSide));

        var bestPath = FindBestCachedPath(ytdPath, mode, out var bestSide);

        if (bestPath == null)

            return null;

        if (bestSide < ThumbnailRender.MaxThumbnailSide && bestSide < need)

            return null;

        return bestPath;

    }



    internal static void StorePng(string ytdPath, int size, string renderedPng, string mode = "")

    {

        _ = size;

        var cachePath = CacheFilePath(ytdPath, ThumbnailRender.MaxThumbnailSide, mode);

        if (cachePath == null || !File.Exists(renderedPng))

            return;



        try

        {

            Directory.CreateDirectory(Path.GetDirectoryName(cachePath)!);

            File.Copy(renderedPng, cachePath, overwrite: true);

        }

        catch

        {

            // ignore

        }

    }



    private static string? FindBestCachedPath(string ytdPath, string mode, out int bestSide)

    {

        bestSide = 0;

        string? bestPath = null;



        foreach (var side in LegacyLookupSizes)

        {

            var path = CacheFilePath(ytdPath, side, mode);

            if (!IsValidCacheFile(path))

                continue;

            if (side > bestSide)

            {

                bestSide = side;

                bestPath = path;

            }

        }



        return bestPath;

    }



    private static bool IsValidCacheFile(string? path)

    {

        if (path == null || !File.Exists(path))

            return false;

        try

        {

            return new FileInfo(path).Length > 512;

        }

        catch

        {

            return false;

        }

    }



    private static string? CacheFilePath(string ytdPath, int size, string mode = "")

    {

        try

        {

            var fi = new FileInfo(ytdPath);

            if (!fi.Exists)

                return null;



            var key = CacheKey(fi);

            var tag = string.IsNullOrEmpty(mode) ? "" : $"{mode}_";

            return Path.Combine(CacheDir(), $"{key}_{tag}{size}.png");

        }

        catch

        {

            return null;

        }

    }



    private static string CacheKey(FileInfo fi)

    {

        // Content fingerprint — Explorer stream copies share cache with real files.
        return AssetFingerprint.Describe(fi.FullName).Hash8;

    }


}


