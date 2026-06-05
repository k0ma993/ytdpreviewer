using System;

using System.Drawing;

using System.IO;

using System.Runtime.InteropServices;

using SharpShell.Attributes;

using SharpShell.Helpers;

using SharpShell.SharpThumbnailHandler;



namespace YtdThumbnail;



/// <summary>

/// Explorer thumbnail handler (stream). Disk cache uses file content fingerprint.

/// </summary>

[ComVisible(true)]
[Guid("8f3c2a1e-9d4b-4e67-b102-7e5d4a3b2c10")]
[COMServerAssociation(AssociationType.ClassOfExtension, ".ytd")]
public sealed class YtdSharpHandler : SharpThumbnailHandler
{
    protected override Bitmap GetThumbnailImage(uint width)
    {
        var side = (int)Math.Max(32, width);
        var sourcePath = TryGetSourcePath();

        if (!string.IsNullOrEmpty(sourcePath))
        {
            try
            {
                var direct = ThumbnailRender.RenderToBitmap(sourcePath, side);
                if (direct != null)
                {
                    ThumbnailBackgroundWarm.Schedule(sourcePath, side);
                    return ThumbnailRender.FitSquare(direct, side);
                }
            }
            catch (Exception ex)
            {
                ThumbnailRender.Log("YtdSharp direct EX " + ex.Message);
            }
        }

        var temp = Path.Combine(Path.GetTempPath(), "ytdprev_" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var file = File.Create(temp))
            {
                SelectedItemStream.Position = 0;
                SelectedItemStream.CopyTo(file);
            }

            var bmp = ThumbnailRender.RenderToBitmap(temp, side);
            if (bmp != null)
            {
                if (!string.IsNullOrEmpty(sourcePath))
                    ThumbnailBackgroundWarm.Schedule(sourcePath, side);
                return ThumbnailRender.FitSquare(bmp, side);
            }
        }
        catch (Exception ex)
        {
            ThumbnailRender.Log("YtdSharp EX " + ex.Message);
        }
        finally
        {
            try
            {
                if (File.Exists(temp))
                    File.Delete(temp);
            }
            catch
            {
                // ignore
            }
        }

        return ThumbnailRender.FallbackBitmap("ytd.ico", side) ?? new Bitmap(side, side);
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

}

