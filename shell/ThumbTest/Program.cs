using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using YtdThumbnail;

namespace ThumbTest;

internal static class Program
{
    private const uint StgmRead = 0;

    private static int Main(string[] args)
    {
        if (args.Length < 1)
        {
            Console.WriteLine("Usage: ThumbTest.exe <file.ytd>");
            return 1;
        }

        var path = Path.GetFullPath(args[0]);
        if (!File.Exists(path))
        {
            Console.Error.WriteLine("File not found: " + path);
            return 2;
        }

        Console.WriteLine("File: " + path);

        try
        {
            var p1 = new ThumbnailProvider();
            p1.Initialize(path, 0);
            p1.GetThumbnail(256, out var hb1, out var a1);
            Console.WriteLine("File init OK: hbmp=" + hb1 + ", alpha=" + a1);
        }
        catch (Exception ex)
        {
            Console.WriteLine("File init FAIL: " + ex.Message);
        }

        try
        {
            var hr = Native.SHCreateStreamOnFileEx(path, StgmRead, 0, false, IntPtr.Zero, out var stream);
            if (hr != 0)
            {
                Console.WriteLine("SHCreateStreamOnFileEx hr=" + hr);
                return 3;
            }
            var p2 = new ThumbnailProvider();
            p2.Initialize(stream, 0);
            p2.GetThumbnail(256, out var hb2, out var a2);
            Console.WriteLine("Stream init OK: hbmp=" + hb2 + ", alpha=" + a2);
        }
        catch (Exception ex)
        {
            Console.WriteLine("Stream init FAIL: " + ex.Message);
        }

        return 0;
    }

    private static class Native
    {
        [DllImport("shlwapi.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        public static extern int SHCreateStreamOnFileEx(
            string pszFile,
            uint grfMode,
            uint dwAttributes,
            bool fCreate,
            IntPtr pSecurity,
            out IStream ppstm);
    }
}
