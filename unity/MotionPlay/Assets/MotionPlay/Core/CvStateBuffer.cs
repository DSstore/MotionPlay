using System;
using System.Collections.Generic;

namespace MotionPlay.Networking
{
    /// <summary>Immutable main-thread view; expired states never expose a position.</summary>
    public sealed class ReceiverSnapshot
    {
        public CvState State { get; }
        public double? AgeSeconds { get; }
        public long Accepted { get; }
        public long Invalid { get; }
        public long Rejected { get; }
        public bool Tracking => State != null && State.Tracking;

        internal ReceiverSnapshot(CvState state, double? age, long accepted, long invalid, long rejected)
        {
            State = state; AgeSeconds = age; Accepted = accepted; Invalid = invalid; Rejected = rejected;
        }
    }

    /// <summary>One latest state, sequence ordering, and bounded stream retirement.</summary>
    public sealed class CvStateBuffer
    {
        private const int MaxRetiredStreams = 128;
        private readonly object gate = new object();
        private readonly double timeout;
        private readonly HashSet<string> retired = new HashSet<string>();
        private CvState latest;
        private double receivedAt;
        private long accepted, invalid, rejected;

        public CvStateBuffer(double timeoutSeconds)
        {
            if (!Finite(timeoutSeconds) || timeoutSeconds <= 0)
                throw new ArgumentOutOfRangeException(nameof(timeoutSeconds));
            timeout = timeoutSeconds;
        }

        public bool TryAccept(CvState state, double now)
        {
            if (state == null) throw new ArgumentNullException(nameof(state));
            if (!Finite(now) || now < 0) throw new ArgumentOutOfRangeException(nameof(now));
            lock (gate)
            {
                if (latest != null)
                {
                    if (now < receivedAt) throw new ArgumentException("Receive clock moved backward.");
                    if (state.StreamId == latest.StreamId)
                    {
                        if (state.Sequence <= latest.Sequence) { rejected++; return false; }
                    }
                    else
                    {
                        // A live stream owns the receiver until it is silent for
                        // the timeout. This prevents two senders alternating control.
                        if (retired.Contains(state.StreamId) || now - receivedAt < timeout ||
                            retired.Count >= MaxRetiredStreams) { rejected++; return false; }
                        retired.Add(latest.StreamId);
                    }
                }
                else if (retired.Contains(state.StreamId)) { rejected++; return false; }
                latest = state;
                receivedAt = now;
                accepted++;
                return true;
            }
        }

        public void RecordInvalid() { lock (gate) invalid++; }

        public ReceiverSnapshot Read(double now)
        {
            if (!Finite(now) || now < 0) throw new ArgumentOutOfRangeException(nameof(now));
            lock (gate)
            {
                double? age = latest == null ? (double?)null : Math.Max(0, now - receivedAt);
                // A reader may sample its clock just before a worker accepts a
                // newer packet. Clamp its age to zero, rather than rejecting it.
                CvState fresh = latest != null && age.Value < timeout ? latest : null;
                return new ReceiverSnapshot(fresh, age, accepted, invalid, rejected);
            }
        }

        public void ClearState() { lock (gate) latest = null; }

        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
    }
}
