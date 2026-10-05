using System;
using System.Collections.Generic;

namespace MotionPlay.Networking
{
    public enum DeliveryState { Idle, Sending, Confirmed, Rejected, NotConfirmed }

    /// <summary>
    /// Retry bookkeeping for result delivery over UDP, with no sockets or clock of its own so it is
    /// testable. Results are sent one at a time, oldest first. A result is confirmed only by a matching
    /// acknowledgement; if none arrives after every attempt it is reported as not confirmed rather than
    /// assumed delivered. The caller keeps the clock (seconds, any monotonic origin).
    /// </summary>
    public sealed class ResultDelivery
    {
        private sealed class Entry
        {
            public string SessionId; public byte[] Payload; public int Attempts; public double NextSend;
        }

        private readonly Queue<Entry> queue = new Queue<Entry>();
        private readonly int maxAttempts;
        private readonly double retrySeconds;

        public ResultDelivery(int maxAttempts = 5, double retrySeconds = 1.0)
        {
            if (maxAttempts < 1) throw new ArgumentException("maxAttempts must be at least 1.");
            if (double.IsNaN(retrySeconds) || double.IsInfinity(retrySeconds) || retrySeconds <= 0)
                throw new ArgumentException("retrySeconds must be finite and positive.");
            this.maxAttempts = maxAttempts; this.retrySeconds = retrySeconds;
        }

        /// <summary>State of the most recently submitted result.</summary>
        public DeliveryState State { get; private set; } = DeliveryState.Idle;
        public string LastSessionId { get; private set; }
        public int Pending => queue.Count;
        /// <summary>Attempts made so far for the result at the front of the queue.</summary>
        public int CurrentAttempts => queue.Count > 0 ? queue.Peek().Attempts : 0;

        public void Submit(string sessionId, byte[] payload, double now)
        {
            if (string.IsNullOrEmpty(sessionId) || payload == null || payload.Length == 0)
                throw new ArgumentException("A session id and payload are required.");
            queue.Enqueue(new Entry { SessionId = sessionId, Payload = payload, NextSend = now });
            LastSessionId = sessionId;
            State = DeliveryState.Sending;
        }

        /// <summary>Return the datagram to send now, or null if nothing is due.</summary>
        public byte[] Poll(double now)
        {
            while (queue.Count > 0)
            {
                Entry head = queue.Peek();
                if (now < head.NextSend) return null;
                if (head.Attempts >= maxAttempts)
                {
                    queue.Dequeue();
                    if (head.SessionId == LastSessionId) State = DeliveryState.NotConfirmed;
                    continue;
                }
                head.Attempts++;
                head.NextSend = now + retrySeconds;
                return head.Payload;
            }
            return null;
        }

        /// <summary>Apply an acknowledgement. Unknown or stale session ids are ignored.</summary>
        public void OnAck(string sessionId, AckStatus status)
        {
            if (queue.Count == 0 || queue.Peek().SessionId != sessionId) return;
            if (status == AckStatus.Error) return; // Receiver could not store it; keep retrying.
            queue.Dequeue();
            if (sessionId == LastSessionId)
                State = status == AckStatus.Rejected ? DeliveryState.Rejected : DeliveryState.Confirmed;
        }
    }
}
