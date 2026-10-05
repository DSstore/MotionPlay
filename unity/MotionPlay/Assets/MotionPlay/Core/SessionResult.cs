using System;
using System.Globalization;
using System.IO;
using System.Text;
using MotionPlay.Games;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace MotionPlay.Networking
{
    /// <summary>One finished round, in the shape of the Python SESSION_END message.</summary>
    public sealed class SessionResult
    {
        public string StreamId { get; set; }
        public long Sequence { get; set; }
        public long Timestamp { get; set; }
        public string SessionId { get; set; }
        public string Game { get; set; }
        public string Hand { get; set; }
        public string Difficulty { get; set; }
        public long StartedAt { get; set; }
        public long EndedAt { get; set; }

        public int Score { get; set; }
        public int TargetsAttempted { get; set; }
        public int TargetsCompleted { get; set; }
        public int CurrentStreak { get; set; }
        public int BestStreak { get; set; }
        public double Duration { get; set; }
        public double? Accuracy { get; set; }
        public double? AverageReactionTime { get; set; }
        public double? AverageMovementTime { get; set; }
        public double? AverageHoldStability { get; set; }
        public double? PathEfficiency { get; set; }

        /// <summary>Copy a finished round's statistics. Envelope fields come from the sender.</summary>
        public static SessionResult FromStats(ReachGardenStats stats, string game, string hand, string difficulty,
            string sessionId, long startedAtMs, long endedAtMs)
        {
            if (stats == null) throw new ArgumentNullException(nameof(stats));
            return new SessionResult
            {
                SessionId = sessionId, Game = game, Hand = hand, Difficulty = difficulty,
                StartedAt = startedAtMs, EndedAt = Math.Max(startedAtMs, endedAtMs),
                Score = stats.Score, TargetsAttempted = stats.Attempted, TargetsCompleted = stats.Watered,
                CurrentStreak = stats.CurrentStreak, BestStreak = stats.BestStreak,
                Duration = stats.DurationSeconds, Accuracy = stats.Accuracy,
                AverageReactionTime = stats.AverageReactionTime, AverageMovementTime = stats.AverageMovementTime,
                AverageHoldStability = stats.AverageHoldStability, PathEfficiency = stats.AveragePathEfficiency
            };
        }
    }

    public enum AckStatus { Stored, Duplicate, Rejected, Error }

    /// <summary>Encode SESSION_END and decode RESULT_ACK (docs/udp_protocol.md); no engine types.</summary>
    public static class SessionResultCodec
    {
        public const int MaxDatagramBytes = 1200;
        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

        public static byte[] Encode(SessionResult result)
        {
            if (result == null) throw new ArgumentNullException(nameof(result));
            var json = new JObject
            {
                ["type"] = "SESSION_END", ["version"] = 1,
                ["stream_id"] = result.StreamId, ["sequence"] = result.Sequence, ["timestamp"] = result.Timestamp,
                ["session_id"] = result.SessionId, ["game"] = result.Game, ["hand"] = result.Hand,
                ["difficulty"] = result.Difficulty, ["startedAt"] = result.StartedAt, ["endedAt"] = result.EndedAt,
                ["duration"] = Finite(result.Duration),
                ["score"] = result.Score, ["targetsAttempted"] = result.TargetsAttempted,
                ["targetsCompleted"] = result.TargetsCompleted, ["currentStreak"] = result.CurrentStreak,
                ["bestStreak"] = result.BestStreak,
                ["accuracy"] = Nullable(result.Accuracy),
                ["averageReactionTime"] = Nullable(result.AverageReactionTime),
                ["averageMovementTime"] = Nullable(result.AverageMovementTime),
                ["averageHoldStability"] = Nullable(result.AverageHoldStability),
                ["pathEfficiency"] = Nullable(result.PathEfficiency)
            };
            byte[] bytes = StrictUtf8.GetBytes(json.ToString(Formatting.None));
            if (bytes.Length > MaxDatagramBytes) throw new InvalidOperationException("SESSION_END is too large.");
            return bytes;
        }

        public static bool TryDecodeAck(byte[] bytes, int count, out string sessionId, out AckStatus status)
        {
            sessionId = null; status = AckStatus.Error;
            if (bytes == null || count < 1 || count > MaxDatagramBytes || count > bytes.Length) return false;
            try
            {
                var root = JToken.Parse(StrictUtf8.GetString(bytes, 0, count)) as JObject;
                if (root == null || (string)root["type"] != "RESULT_ACK" || (int?)root["version"] != 1) return false;
                string id = (string)root["session_id"];
                if (!Guid.TryParseExact(id, "D", out Guid parsed) || parsed.ToString("D") != id) return false;
                switch ((string)root["status"])
                {
                    case "stored": status = AckStatus.Stored; break;
                    case "duplicate": status = AckStatus.Duplicate; break;
                    case "rejected": status = AckStatus.Rejected; break;
                    case "error": status = AckStatus.Error; break;
                    default: return false;
                }
                sessionId = id;
                return true;
            }
            catch (Exception error) when (error is JsonException || error is ArgumentException ||
                                          error is InvalidCastException || error is FormatException)
            {
                return false;
            }
        }

        private static double Finite(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value)) throw new ArgumentException("Metric must be finite.");
            return value;
        }

        private static JToken Nullable(double? value) => value.HasValue ? new JValue(Finite(value.Value)) : JValue.CreateNull();
    }
}
