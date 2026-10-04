using System;
using MotionPlay.Networking;

namespace MotionPlay.Control
{
    /// <summary>Camera-plane limits for the cursor center, in Unity world units.</summary>
    public sealed class CursorArea
    {
        public double Left { get; }
        public double Right { get; }
        public double Bottom { get; }
        public double Top { get; }

        private CursorArea(double halfWidth, double halfHeight)
        {
            Left = -halfWidth; Right = halfWidth; Bottom = -halfHeight; Top = halfHeight;
        }

        /// <summary>Inset an orthographic view by the disc radius plus an edge margin.</summary>
        public static CursorArea ForOrthographic(double halfHeight, double aspect, double radius, double margin)
        {
            if (!Finite(halfHeight) || halfHeight <= 0 || !Finite(aspect) || aspect <= 0 ||
                !Finite(radius) || radius <= 0 || !Finite(margin) || margin < 0)
                throw new ArgumentException("Cursor view needs finite positive size/aspect/radius and a nonnegative margin.");
            double inset = radius + margin;
            double halfWidth = halfHeight * aspect;
            if (!Finite(inset) || !Finite(halfWidth) || inset >= halfWidth || inset >= halfHeight)
                throw new ArgumentException("The camera view is too small for the cursor radius and margin.");
            return new CursorArea(halfWidth - inset, halfHeight - inset);
        }

        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
    }

    /// <summary>A current point in the camera plane; never a cached or depth-driven position.</summary>
    public sealed class CursorPoint
    {
        public double X { get; }
        public double Y { get; }
        internal CursorPoint(double x, double y) { X = x; Y = y; }
    }

    public static class CursorMapper
    {
        /// <summary>Map only fresh tracked snapshots. Y becomes upward; mirroring is applied once.</summary>
        public static bool TryMap(ReceiverSnapshot snapshot, CursorArea area, bool mirrorControl, out CursorPoint point)
        {
            if (area == null) throw new ArgumentNullException(nameof(area));
            point = null;
            CvState state = snapshot?.State;
            if (state == null || !state.Tracking || state.Position == null) return false;
            double x = state.Position.X;
            if (mirrorControl != state.Mirrored) x = 1 - x;
            // The weighted form avoids overflowing Right-Left for extreme views.
            double mappedX = (1 - x) * area.Left + x * area.Right;
            double mappedY = (1 - state.Position.Y) * area.Top + state.Position.Y * area.Bottom;
            point = new CursorPoint(mappedX, mappedY);
            return true;
        }
    }
}
