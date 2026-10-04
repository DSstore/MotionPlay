namespace MotionPlay.Networking
{
    /// <summary>Immutable normalized palm position; Z is model depth, not meters.</summary>
    public sealed class PalmPosition
    {
        public double X { get; }
        public double Y { get; }
        public double Z { get; }

        internal PalmPosition(double x, double y, double z) { X = x; Y = y; Z = z; }
    }

    /// <summary>A validated CV_STATE packet independent of Unity or gameplay.</summary>
    public sealed class CvState
    {
        public string StreamId { get; }
        public long Sequence { get; }
        public long Timestamp { get; }
        public string Hand { get; }
        public bool Tracking { get; }
        public PalmPosition Position { get; }
        public string Gesture { get; }
        public double Confidence { get; }
        public bool Mirrored { get; }

        internal CvState(string streamId, long sequence, long timestamp, string hand,
            bool tracking, PalmPosition position, string gesture, double confidence, bool mirrored)
        {
            StreamId = streamId; Sequence = sequence; Timestamp = timestamp; Hand = hand;
            Tracking = tracking; Position = position; Gesture = gesture;
            Confidence = confidence; Mirrored = mirrored;
        }
    }
}
