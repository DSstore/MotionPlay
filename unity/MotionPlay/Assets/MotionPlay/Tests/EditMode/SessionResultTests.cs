using System;
using System.Linq;
using System.Text;
using MotionPlay.Games;
using MotionPlay.Networking;
using Newtonsoft.Json.Linq;
using NUnit.Framework;

namespace MotionPlay.Tests
{
    public sealed class SessionResultTests
    {
        private const string Session = "c3e333c3-3333-4333-8333-333333333333";

        private static SessionResult Sample() => new SessionResult
        {
            StreamId = "b2e222b2-2222-4222-8222-222222222222", Sequence = 4, Timestamp = 1770000001000,
            SessionId = Session, Game = "reach_garden", Hand = "right", Difficulty = "default",
            StartedAt = 1770000000000, EndedAt = 1770000060000, Duration = 60.5,
            Score = 6, TargetsAttempted = 8, TargetsCompleted = 6, CurrentStreak = 2, BestStreak = 4,
            Accuracy = 0.75, AverageReactionTime = 0.4, AverageMovementTime = 1.1,
            AverageHoldStability = 0.9, PathEfficiency = null
        };

        private static byte[] Ack(string status, string id = Session) => Encoding.UTF8.GetBytes(
            "{\"type\":\"RESULT_ACK\",\"version\":1,\"session_id\":\"" + id + "\",\"status\":\"" + status + "\"}");

        [Test]
        public void EncodesTheSharedFieldSetWithExplicitNulls()
        {
            JObject json = JObject.Parse(Encoding.UTF8.GetString(SessionResultCodec.Encode(Sample())));
            string[] expected =
            {
                "type", "version", "stream_id", "sequence", "timestamp", "session_id", "game", "hand", "difficulty",
                "startedAt", "endedAt", "duration", "score", "targetsAttempted", "targetsCompleted", "currentStreak",
                "bestStreak", "accuracy", "averageReactionTime", "averageMovementTime", "averageHoldStability",
                "pathEfficiency"
            };
            CollectionAssert.AreEquivalent(expected, json.Properties().Select(p => p.Name).ToArray());
            Assert.AreEqual("SESSION_END", (string)json["type"]);
            Assert.AreEqual(JTokenType.Null, json["pathEfficiency"].Type);
            Assert.AreEqual(JTokenType.Integer, json["sequence"].Type);
            Assert.AreEqual(0.75, (double)json["accuracy"], 1e-12);
        }

        [Test]
        public void RefusesNonFiniteMetrics()
        {
            SessionResult result = Sample();
            result.Accuracy = double.NaN;
            Assert.Throws<ArgumentException>(() => SessionResultCodec.Encode(result));
            result = Sample();
            result.Duration = double.PositiveInfinity;
            Assert.Throws<ArgumentException>(() => SessionResultCodec.Encode(result));
        }

        [Test]
        public void BuildsAResultFromRoundStatistics()
        {
            var game = new ReachGardenGame(new ReachGardenSettings { TargetCount = 1 }, 3.0, 2.0, 7);
            game.Step(1.0 / 30, true, 0, 0);
            for (int i = 0; i < 300 && game.Phase == ReachGardenPhase.Playing; i++)
                game.Step(1.0 / 30, true, game.TargetX, game.TargetY);
            Assert.AreEqual(ReachGardenPhase.Complete, game.Phase);

            SessionResult result = SessionResult.FromStats(game.Stats, "reach_garden", "left", "default", Session, 1000, 500);
            Assert.AreEqual(1, result.TargetsAttempted);
            Assert.AreEqual(1, result.TargetsCompleted);
            Assert.AreEqual(1, result.Score);
            Assert.AreEqual(1.0, result.Accuracy.Value, 1e-9);
            Assert.AreEqual(1000, result.StartedAt);
            Assert.AreEqual(1000, result.EndedAt, "endedAt is never earlier than startedAt");
            Assert.AreEqual(game.Stats.DurationSeconds, result.Duration, 1e-12);
        }

        [Test]
        public void DecodesEveryAckStatusAndRejectsBadOnes()
        {
            var expected = new[] { "stored", "duplicate", "rejected", "error" };
            var statuses = new[] { AckStatus.Stored, AckStatus.Duplicate, AckStatus.Rejected, AckStatus.Error };
            for (int i = 0; i < expected.Length; i++)
            {
                byte[] bytes = Ack(expected[i]);
                Assert.IsTrue(SessionResultCodec.TryDecodeAck(bytes, bytes.Length, out string id, out AckStatus status));
                Assert.AreEqual(Session, id);
                Assert.AreEqual(statuses[i], status);
            }
            foreach (byte[] bad in new[]
            {
                Ack("maybe"), Ack("stored", "not-a-uuid"), Encoding.UTF8.GetBytes("{}"),
                Encoding.UTF8.GetBytes("garbage"), Encoding.UTF8.GetBytes("[]"), new byte[0]
            })
                Assert.IsFalse(SessionResultCodec.TryDecodeAck(bad, bad.Length, out _, out _));
        }

        [Test]
        public void RetriesOnScheduleUntilAcknowledged()
        {
            var delivery = new ResultDelivery(3, 1.0);
            byte[] payload = { 1, 2, 3 };
            delivery.Submit(Session, payload, 10);
            Assert.AreEqual(DeliveryState.Sending, delivery.State);
            Assert.AreSame(payload, delivery.Poll(10));
            Assert.IsNull(delivery.Poll(10.5), "not due yet");
            Assert.AreSame(payload, delivery.Poll(11));
            Assert.AreEqual(2, delivery.CurrentAttempts);

            delivery.OnAck(Session, AckStatus.Stored);
            Assert.AreEqual(DeliveryState.Confirmed, delivery.State);
            Assert.IsNull(delivery.Poll(20));
            Assert.AreEqual(0, delivery.Pending);
        }

        [Test]
        public void ReportsNotConfirmedAfterTheLastAttempt()
        {
            var delivery = new ResultDelivery(2, 1.0);
            delivery.Submit(Session, new byte[] { 1 }, 0);
            Assert.IsNotNull(delivery.Poll(0));
            Assert.IsNotNull(delivery.Poll(1));
            Assert.IsNull(delivery.Poll(2));
            Assert.AreEqual(DeliveryState.NotConfirmed, delivery.State);
            Assert.AreEqual(0, delivery.Pending);
        }

        [Test]
        public void ErrorAckKeepsRetryingButDuplicateAndRejectedAreFinal()
        {
            var delivery = new ResultDelivery(5, 1.0);
            delivery.Submit(Session, new byte[] { 1 }, 0);
            delivery.Poll(0);
            delivery.OnAck(Session, AckStatus.Error);
            Assert.AreEqual(DeliveryState.Sending, delivery.State);
            Assert.IsNotNull(delivery.Poll(1));
            delivery.OnAck(Session, AckStatus.Duplicate);
            Assert.AreEqual(DeliveryState.Confirmed, delivery.State);

            const string other = "d4e444d4-4444-4444-8444-444444444444";
            delivery.Submit(other, new byte[] { 2 }, 5);
            delivery.Poll(5);
            delivery.OnAck(other, AckStatus.Rejected);
            Assert.AreEqual(DeliveryState.Rejected, delivery.State);
        }

        [Test]
        public void IgnoresStaleAcksAndSendsResultsInOrder()
        {
            const string second = "d4e444d4-4444-4444-8444-444444444444";
            var delivery = new ResultDelivery(5, 1.0);
            byte[] first = { 1 }, next = { 2 };
            delivery.Submit(Session, first, 0);
            delivery.Submit(second, next, 0);
            Assert.AreSame(first, delivery.Poll(0));
            delivery.OnAck(second, AckStatus.Stored);
            Assert.AreEqual(2, delivery.Pending, "an ack for a result that is not at the front changes nothing");
            delivery.OnAck(Session, AckStatus.Stored);
            Assert.AreEqual(DeliveryState.Sending, delivery.State, "the latest submitted result is still pending");
            Assert.AreSame(next, delivery.Poll(0));
            delivery.OnAck(second, AckStatus.Stored);
            Assert.AreEqual(DeliveryState.Confirmed, delivery.State);
        }

        [Test]
        public void ValidatesDeliveryArguments()
        {
            Assert.Throws<ArgumentException>(() => new ResultDelivery(0, 1));
            Assert.Throws<ArgumentException>(() => new ResultDelivery(1, 0));
            Assert.Throws<ArgumentException>(() => new ResultDelivery(1, double.NaN));
            var delivery = new ResultDelivery();
            Assert.Throws<ArgumentException>(() => delivery.Submit("", new byte[] { 1 }, 0));
            Assert.Throws<ArgumentException>(() => delivery.Submit(Session, new byte[0], 0));
        }

        [Test]
        public void ConfigurationExposesTheResultPort()
        {
            Assert.AreEqual(5006, new ReceiverConfiguration().ResultPort);
            Assert.AreEqual(6000, ReceiverConfiguration.Load(null, name => name == "UNITY_TO_PYTHON_PORT" ? "6000" : null).ResultPort);
            Assert.Throws<ArgumentException>(() => new ReceiverConfiguration(5005, 0.5, 5005));
            Assert.Throws<ArgumentException>(() => ReceiverConfiguration.Load(null, name => name == "UNITY_TO_PYTHON_PORT" ? "80" : null));
        }
    }
}
