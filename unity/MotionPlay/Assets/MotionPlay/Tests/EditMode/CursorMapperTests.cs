using System;
using MotionPlay.Control;
using MotionPlay.Networking;
using NUnit.Framework;

namespace MotionPlay.Tests
{
    public sealed class CursorMapperTests
    {
        [Test]
        public void CenterMapsToCameraPlaneCenter()
        {
            Assert.IsTrue(CursorMapper.TryMap(Snapshot(0.5, 0.5), Area(), true, out CursorPoint point));
            Assert.AreEqual(0, point.X, 1e-12);
            Assert.AreEqual(0, point.Y, 1e-12);
        }

        [TestCase(0, 0, -3.8, 2.8)]
        [TestCase(1, 0, 3.8, 2.8)]
        [TestCase(0, 1, -3.8, -2.8)]
        [TestCase(1, 1, 3.8, -2.8)]
        public void ImageCornersMapToInsetViewCornersWithUpwardY(double x, double y, double expectedX, double expectedY)
        {
            Assert.IsTrue(CursorMapper.TryMap(Snapshot(x, y), Area(), true, out CursorPoint point));
            Assert.AreEqual(expectedX, point.X, 1e-12);
            Assert.AreEqual(expectedY, point.Y, 1e-12);
        }

        [TestCase(true, true, -1.9)]
        [TestCase(false, true, 1.9)]
        [TestCase(true, false, 1.9)]
        [TestCase(false, false, -1.9)]
        public void MirrorOrientationUsesPacketFlagExactlyOnce(bool packetMirrored, bool desiredMirror, double expectedX)
        {
            Assert.IsTrue(CursorMapper.TryMap(Snapshot(0.25, 0.75, packetMirrored), Area(), desiredMirror, out CursorPoint point));
            Assert.AreEqual(expectedX, point.X, 1e-12);
            Assert.AreEqual(-1.4, point.Y, 1e-12);
        }

        [Test]
        public void RadiusAndMarginKeepEntireDiscWithinTheView()
        {
            CursorArea area = Area();
            Assert.AreEqual(4, area.Right + 0.12 + 0.08, 1e-12);
            Assert.AreEqual(3, area.Top + 0.12 + 0.08, 1e-12);
            for (int x = 0; x <= 10; x++)
                for (int y = 0; y <= 10; y++)
                {
                    Assert.IsTrue(CursorMapper.TryMap(Snapshot(x / 10.0, y / 10.0), area, true, out CursorPoint point));
                    Assert.That(point.X, Is.InRange(area.Left, area.Right));
                    Assert.That(point.Y, Is.InRange(area.Bottom, area.Top));
                }
        }

        [Test]
        public void AspectAndCameraSizeChangesRemapWithoutChangingNormalizedInput()
        {
            var snapshot = Snapshot(1, 0);
            CursorMapper.TryMap(snapshot, Area(), true, out CursorPoint landscape);
            CursorMapper.TryMap(snapshot, CursorArea.ForOrthographic(3, 0.5, 0.12, 0.08), true, out CursorPoint portrait);
            Assert.AreEqual(3.8, landscape.X, 1e-12);
            Assert.AreEqual(1.3, portrait.X, 1e-12);
            Assert.AreEqual(landscape.Y, portrait.Y);
            CursorMapper.TryMap(snapshot, CursorArea.ForOrthographic(5, 1, 0.12, 0.08), true, out CursorPoint larger);
            Assert.AreEqual(4.8, larger.X, 1e-12);
            Assert.AreEqual(1, snapshot.State.Position.X);
        }

        [Test]
        public void UnavailableLostAndExpiredSnapshotsNeverReturnOldPosition()
        {
            Assert.IsFalse(CursorMapper.TryMap(null, Area(), true, out CursorPoint missing));
            Assert.IsNull(missing);
            Assert.IsFalse(CursorMapper.TryMap(Snapshot(0, 0, tracking: false), Area(), true, out CursorPoint lost));
            Assert.IsNull(lost);
            var buffer = new CvStateBuffer(0.5);
            buffer.TryAccept(PacketFixture.State(), 0);
            Assert.IsTrue(CursorMapper.TryMap(buffer.Read(0.499), Area(), true, out _));
            Assert.IsFalse(CursorMapper.TryMap(buffer.Read(0.5), Area(), true, out CursorPoint expired));
            Assert.IsNull(expired);
        }

        [Test]
        public void ReacquisitionMapsTheNewPositionImmediately()
        {
            var buffer = new CvStateBuffer(0.5);
            buffer.TryAccept(PacketFixture.State(), 0);
            Assert.IsFalse(CursorMapper.TryMap(buffer.Read(1), Area(), true, out _));
            buffer.TryAccept(PacketFixture.State(1), 1);
            Assert.IsTrue(CursorMapper.TryMap(buffer.Read(1), Area(), true, out CursorPoint point));
            Assert.AreEqual(0.38, point.X, 1e-12);
        }

        [Test]
        public void UnknownGestureDoesNotBlockMovementAndModelDepthDoesNotDriveIt()
        {
            var json = PacketFixture.Json();
            json["gesture"] = "UNKNOWN";
            json["position"]["z"] = -100;
            byte[] bytes = PacketFixture.Bytes(json);
            Assert.IsTrue(CvStateCodec.TryDecode(bytes, bytes.Length, out CvState state));
            var buffer = new CvStateBuffer(0.5); buffer.TryAccept(state, 0);
            Assert.IsTrue(CursorMapper.TryMap(buffer.Read(0), Area(), true, out CursorPoint point));
            Assert.AreEqual(0.38, point.X, 1e-12);
            Assert.AreEqual(1.064, point.Y, 1e-12);
        }

        [TestCase(0, 1, 0.12, 0.08)]
        [TestCase(3, 0, 0.12, 0.08)]
        [TestCase(3, 1, 0, 0.08)]
        [TestCase(3, 1, 0.12, -0.08)]
        [TestCase(3, 1, 3, 0)]
        [TestCase(3, 0.01, 0.12, 0.08)]
        public void InvalidOrTooSmallViewIsRejected(double halfHeight, double aspect, double radius, double margin)
        {
            Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(halfHeight, aspect, radius, margin));
        }

        [Test]
        public void NonfiniteAndOverflowingDimensionsAreRejected()
        {
            foreach (double value in new[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity })
            {
                Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(value, 1, 0.12, 0.08));
                Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(3, value, 0.12, 0.08));
                Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(3, 1, value, 0.08));
                Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(3, 1, 0.12, value));
            }
            Assert.Throws<ArgumentException>(() => CursorArea.ForOrthographic(double.MaxValue, 2, 1, 0));
            Assert.Throws<ArgumentNullException>(() => CursorMapper.TryMap(Snapshot(0, 0), null, true, out _));
        }

        private static CursorArea Area() => CursorArea.ForOrthographic(3, 4.0 / 3, 0.12, 0.08);

        private static ReceiverSnapshot Snapshot(double x, double y, bool mirrored = true, bool tracking = true)
        {
            var json = PacketFixture.Json(tracking: tracking);
            json["mirrored"] = mirrored;
            if (tracking) { json["position"]["x"] = x; json["position"]["y"] = y; }
            byte[] bytes = PacketFixture.Bytes(json);
            Assert.IsTrue(CvStateCodec.TryDecode(bytes, bytes.Length, out CvState state));
            var buffer = new CvStateBuffer(0.5); buffer.TryAccept(state, 0);
            return buffer.Read(0);
        }
    }
}
