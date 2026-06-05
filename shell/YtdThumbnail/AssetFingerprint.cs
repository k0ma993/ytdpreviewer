using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace YtdThumbnail;

internal readonly struct AssetFingerprint
{
    internal long Length { get; }
    internal uint SampleCrc { get; }
    internal string Ext { get; }
    internal string Hash8 { get; }

    internal AssetFingerprint(long length, uint sampleCrc, string ext, string hash8)
    {
        Length = length;
        SampleCrc = sampleCrc;
        Ext = ext;
        Hash8 = hash8;
    }

    internal static AssetFingerprint Describe(string filePath)
    {
        var fi = new FileInfo(filePath);
        var sample = SampleCrc32(fi);
        var ext = NormalizeAssetExtension(fi);
        var hash8 = Hash8From(fi.Length, sample, ext);
        return new AssetFingerprint(fi.Length, sample, ext, hash8);
    }

    internal bool MatchesFile(string filePath)
    {
        try
        {
            var fi = new FileInfo(filePath);
            if (!fi.Exists || fi.Length != Length)
                return false;
            if (!string.Equals(NormalizeAssetExtension(fi), Ext, StringComparison.OrdinalIgnoreCase))
                return false;
            return SampleCrc32(fi) == SampleCrc;
        }
        catch
        {
            return false;
        }
    }

    private static string NormalizeAssetExtension(FileInfo fi)
    {
        var ext = Path.GetExtension(fi.Name).ToLowerInvariant();
        if (!ext.Equals(".tmp", StringComparison.OrdinalIgnoreCase))
            return ext;

        var name = fi.Name.ToLowerInvariant();
        if (name.StartsWith("yddprev_", StringComparison.Ordinal))
            return ".ydd";
        if (name.StartsWith("ytdprev_", StringComparison.Ordinal))
            return ".ytd";
        return ext;
    }

    private static string Hash8From(long length, uint sample, string ext)
    {
        var material = $"v10|{ext}|{length}|{sample:X8}";
        using var sha = SHA256.Create();
        var hash = sha.ComputeHash(Encoding.UTF8.GetBytes(material));
        return BitConverter.ToString(hash, 0, 8).Replace("-", "");
    }

    private static uint SampleCrc32(FileInfo fi)
    {
        const int sampleLen = 256 * 1024;
        var crc = 0xFFFFFFFFu;
        var buf = new byte[8192];
        using var fs = fi.OpenRead();
        var remaining = (int)Math.Min(sampleLen, fi.Length);
        while (remaining > 0)
        {
            var read = fs.Read(buf, 0, Math.Min(buf.Length, remaining));
            if (read <= 0)
                break;
            for (var i = 0; i < read; i++)
                crc = Crc32Table[(crc ^ buf[i]) & 0xFF] ^ (crc >> 8);
            remaining -= read;
        }
        return crc ^ 0xFFFFFFFFu;
    }

    private static readonly uint[] Crc32Table = CreateCrc32Table();

    private static uint[] CreateCrc32Table()
    {
        var table = new uint[256];
        for (uint i = 0; i < 256; i++)
        {
            var c = i;
            for (var j = 0; j < 8; j++)
                c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        return table;
    }
}
