# Test whether Explorer shell returns a texture thumbnail for a .ytd file.
param(
    [string]$Path = ""
)

Add-Type -AssemblyName System.Drawing

if (-not $Path) {
    $f = Get-ChildItem "$env:USERPROFILE\Desktop" -Filter "*.ytd" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $f) {
        Write-Host "No .ytd found on Desktop. Pass -Path to a .ytd file."
        exit 1
    }
    $Path = $f.FullName
}

$Path = (Resolve-Path $Path).Path
Write-Host "File:" $Path

$code = @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;

public static class ShellThumb {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    public static extern int SHCreateItemFromParsingName(
        string pszPath,
        IntPtr pbc,
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out object ppv);

    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItemImageFactory {
        void GetImage(SIZE size, int flags, out IntPtr phbm, out int pdwAlpha);
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct SIZE { public int cx; public int cy; }

    public const int SIIGBF_RESIZETOFIT = 0x00;
    public const int SIIGBF_THUMBNAILONLY = 0x08;

    public static Bitmap GetThumb(string path, int size) {
        Guid iid = new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b");
        object item;
        int hr = SHCreateItemFromParsingName(path, IntPtr.Zero, iid, out item);
        if (hr != 0) throw new Exception("SHCreateItemFromParsingName hr=" + hr);
        var factory = (IShellItemImageFactory)item;
        IntPtr hbmp;
        int alpha;
        var sz = new SIZE { cx = size, cy = size };
        factory.GetImage(sz, SIIGBF_THUMBNAILONLY | SIIGBF_RESIZETOFIT, out hbmp, out alpha);
        return Image.FromHbitmap(hbmp);
    }
}
'@

Add-Type -TypeDefinition $code -ReferencedAssemblies System.Drawing

try {
    $bmp = [ShellThumb]::GetThumb($Path, 256)
    $out = Join-Path $env:TEMP "ytd_shell_thumb_test.png"
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host "OK: shell thumbnail saved to" $out
    Write-Host "Open the PNG. Green square = run scripts\install_shell_admin.bat as Administrator."
    Write-Host "Check log:" (Join-Path $env:LOCALAPPDATA "YTDPreviewer\thumb.log")
    exit 0
}
catch {
    Write-Host "FAIL:" $_.Exception.Message
    exit 2
}
