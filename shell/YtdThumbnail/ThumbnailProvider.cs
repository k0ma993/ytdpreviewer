using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace YtdThumbnail;

/// <summary>
/// Direct COM tests (ThumbTest). Explorer uses <see cref="YtdSharpHandler"/> via SharpShell.
/// </summary>
public sealed class ThumbnailProvider : IInitializeWithStream, IInitializeWithFile, IThumbnailProvider, IPersistFile, IExtractIconW
{
    private const uint GILPerInstance = 0x0001;

    private string? _path;
    private string? _tempFile;
    private Bitmap? _lastBitmap;

    // --- IInitializeWithStream / IThumbnailProvider ---

    public void Initialize(IStream stream, uint grfMode)
    {
        CleanupTemp();
        _tempFile = Path.Combine(Path.GetTempPath(), "ytdprev_" + Guid.NewGuid().ToString("N") + ".tmp");
        CopyStreamToFile(stream, _tempFile);
        _path = _tempFile;
        ThumbnailRender.Log($"InitStream -> {_tempFile} ({new FileInfo(_tempFile).Length} bytes)");
    }

    public void Initialize(string pszFilePath, uint grfMode)
    {
        CleanupTemp();
        _path = pszFilePath;
        ThumbnailRender.Log("InitFile -> " + pszFilePath);
    }

    public void GetThumbnail(uint cx, out IntPtr phbmp, out WTS_ALPHATYPE pdwAlpha)
    {
        phbmp = IntPtr.Zero;
        pdwAlpha = WTS_ALPHATYPE.WTSAT_UNKNOWN;

        if (string.IsNullOrEmpty(_path) || !File.Exists(_path))
            throw new COMException("File not found", unchecked((int)0x80070002));

        try
        {
            _lastBitmap?.Dispose();
            _lastBitmap = ThumbnailRender.RenderToBitmap(_path, (int)cx);
            if (_lastBitmap == null)
            {
                ThumbnailRender.Log("GetThumbnail FAILED " + _path);
                throw new COMException("Thumbnail render failed", unchecked((int)0x80004005));
            }

            phbmp = _lastBitmap.GetHbitmap();
            pdwAlpha = WTS_ALPHATYPE.WTSAT_ARGB;
            ThumbnailRender.Log($"GetThumbnail OK {_lastBitmap.Width}x{_lastBitmap.Height}");
        }
        catch (Exception ex)
        {
            ThumbnailRender.Log("GetThumbnail EX " + ex.Message);
            throw;
        }
        finally
        {
            CleanupTemp();
        }
    }

    // --- IPersistFile / IExtractIconW (Explorer file icons) ---

    public void GetClassID(out Guid pClassID) => pClassID = new Guid("8f3c2a1e-9d4b-4e67-b102-7e5d4a3b2c10");

    public int IsDirty() => 1;

    public int Load(string pszFileName, uint dwMode)
    {
        _path = pszFileName;
        ThumbnailRender.Log("Icon Load -> " + pszFileName);
        return 0;
    }

    public int Save(string pszFileName, bool fRemember) => unchecked((int)0x80004001);

    public int SaveCompleted(string pszFileName) => 0;

    public int GetCurFile(out string ppszFileName)
    {
        ppszFileName = _path ?? "";
        return string.IsNullOrEmpty(_path) ? unchecked((int)0x80004005) : 0;
    }

    public int GetIconLocation(uint uFlags, StringBuilder pszIconFile, uint cchMax, out int piIndex, out uint pwFlags)
    {
        piIndex = 0;
        pwFlags = GILPerInstance;
        return 1; // S_FALSE — Explorer will call Extract (sync; no GIL_ASYNC)
    }

    public int Extract(string pszFile, uint nIconIndex, out IntPtr phiconLarge, out IntPtr phiconSmall, uint nIconSize)
    {
        phiconLarge = IntPtr.Zero;
        phiconSmall = IntPtr.Zero;

        var path = string.IsNullOrEmpty(pszFile) ? _path : pszFile;
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
            return TryFallbackIcons(out phiconLarge, out phiconSmall, unchecked((int)0x80070002));

        var side = (int)(nIconSize & 0xFFFF);
        if (side <= 0)
            side = 256;

        try
        {
            using var bmp = ThumbnailRender.RenderToBitmap(path, side);
            if (bmp == null)
            {
                ThumbnailRender.Log("Icon Extract FAILED " + path);
                return TryFallbackIcons(out phiconLarge, out phiconSmall, unchecked((int)0x80004005));
            }

            phiconLarge = bmp.GetHicon();
            phiconSmall = NativeMethods.CopyIcon(phiconLarge);
            if (phiconSmall == IntPtr.Zero)
                phiconSmall = phiconLarge;
            ThumbnailRender.Log($"Icon Extract OK {bmp.Width}x{bmp.Height} " + path);
            return 0;
        }
        catch (Exception ex)
        {
            ThumbnailRender.Log("Icon Extract EX " + ex.Message);
            return TryFallbackIcons(out phiconLarge, out phiconSmall, unchecked((int)0x80004005));
        }
    }

    private static int TryFallbackIcons(out IntPtr phiconLarge, out IntPtr phiconSmall, int errorHr)
    {
        phiconLarge = IntPtr.Zero;
        phiconSmall = IntPtr.Zero;
        var ico = Path.Combine(ThumbnailRender.InstallDir(), "assets", "ytd.ico");
        if (!File.Exists(ico))
            return errorHr;

        var count = NativeMethods.ExtractIconEx(ico, 0, out phiconLarge, out phiconSmall, 1);
        if (count == 0 || phiconLarge == IntPtr.Zero)
            return errorHr;

        if (phiconSmall == IntPtr.Zero)
            phiconSmall = NativeMethods.CopyIcon(phiconLarge);
        ThumbnailRender.Log("Icon Extract fallback ytd.ico");
        return 0;
    }

    private void CleanupTemp()
    {
        if (_tempFile == null)
            return;
        try
        {
            if (File.Exists(_tempFile))
                File.Delete(_tempFile);
        }
        catch
        {
            // ignore
        }
        _tempFile = null;
    }

    private static void CopyStreamToFile(IStream stream, string destPath)
    {
        const int seekSet = 0;
        stream.Seek(0, seekSet, IntPtr.Zero);

        using var file = File.Create(destPath);
        var buffer = new byte[1024 * 64];
        var pcb = Marshal.AllocHGlobal(sizeof(int));
        try
        {
            while (true)
            {
                stream.Read(buffer, buffer.Length, pcb);
                var read = Marshal.ReadInt32(pcb);
                if (read <= 0)
                    break;
                file.Write(buffer, 0, read);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(pcb);
        }

        if (new FileInfo(destPath).Length < 16)
            throw new COMException("Empty YTD stream", unchecked((int)0x8007000D));
    }
}

[ComImport]
[Guid("B7D14566-0509-4CCE-A755-4A33F39A1283")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IInitializeWithFile
{
    void Initialize([MarshalAs(UnmanagedType.LPWStr)] string pszFilePath, uint grfMode);
}

[ComImport]
[Guid("B824B49D-22AC-4161-AC8D-3ED3020153F0")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IInitializeWithStream
{
    void Initialize(IStream stream, uint grfMode);
}

[ComImport]
[Guid("E357FCCD-A995-4576-B01F-234630154E96")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IThumbnailProvider
{
    void GetThumbnail(uint cx, out IntPtr phbmp, out WTS_ALPHATYPE pdwAlpha);
}

[ComImport]
[Guid("0000010b-0000-0000-c000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile
{
    void GetClassID(out Guid pClassID);
    [PreserveSig]
    int IsDirty();
    [PreserveSig]
    int Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
    [PreserveSig]
    int Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
    [PreserveSig]
    int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
    [PreserveSig]
    int GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
}

[ComImport]
[Guid("000214fa-0000-0000-c000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IExtractIconW
{
    [PreserveSig]
    int GetIconLocation(
        uint uFlags,
        [MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconFile,
        uint cchMax,
        out int piIndex,
        out uint pwFlags);

    [PreserveSig]
    int Extract(
        [MarshalAs(UnmanagedType.LPWStr)] string pszFile,
        uint nIconIndex,
        out IntPtr phiconLarge,
        out IntPtr phiconSmall,
        uint nIconSize);
}

internal static class NativeMethods
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern uint ExtractIconEx(string lpszFile, int nIconIndex, out IntPtr phiconLarge, out IntPtr phiconSmall, uint nIcons);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr CopyIcon(IntPtr hIcon);
}

public enum WTS_ALPHATYPE
{
    WTSAT_UNKNOWN = 0,
    WTSAT_RGB = 1,
    WTSAT_ARGB = 2,
    WTSAT_PREMULTIPLIED = 3,
}
