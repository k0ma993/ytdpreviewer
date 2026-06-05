using System;
using System.Drawing;
using System.Runtime.InteropServices;
using SharpShell.Attributes;
using SharpShell.SharpThumbnailHandler;

namespace YtdThumbnail;

/// <summary>Legacy COM entry — .ydd thumbnails disabled; instant static icon only.</summary>
[ComVisible(true)]
[Guid("4c8e1f2a-6b3d-4e59-9c01-2f7e6d5a4b3c")]
[COMServerAssociation(AssociationType.ClassOfExtension, ".ydd")]
public sealed class YddSharpHandler : SharpThumbnailHandler
{
    protected override Bitmap GetThumbnailImage(uint width)
    {
        var side = (int)Math.Max(32, width);
        return ThumbnailRender.FallbackBitmap("ydd.ico", side) ?? new Bitmap(side, side);
    }
}
