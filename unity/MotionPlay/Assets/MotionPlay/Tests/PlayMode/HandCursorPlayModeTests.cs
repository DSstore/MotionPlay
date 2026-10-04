using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using MotionPlay.Unity;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace MotionPlay.Tests
{
    /// <summary>Hardware-free Unity lifecycle check; requires the real Unity Test Runner.</summary>
    public sealed class HandCursorPlayModeTests
    {
        [UnityTest]
        public IEnumerator CursorFollowsUdpHidesOnLossTimeoutAndDisable()
        {
            int port;
            using (var probe = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0)))
                port = ((IPEndPoint)probe.Client.LocalEndPoint).Port;
            var savedEnvironment = new Dictionary<string, string>();
            foreach (string name in new[] { "CV_TO_UNITY_PORT", "UNITY_TO_PYTHON_PORT", "UNITY_RECEIVE_TIMEOUT", "MOTIONPLAY_ENV_FILE" })
                savedEnvironment[name] = Environment.GetEnvironmentVariable(name);
            var root = new GameObject("Cursor lifecycle test");
            root.SetActive(false);
            var sender = new UdpClient();
            try
            {
                Environment.SetEnvironmentVariable("CV_TO_UNITY_PORT", port.ToString());
                Environment.SetEnvironmentVariable("UNITY_TO_PYTHON_PORT", port == 5006 ? "5007" : "5006");
                Environment.SetEnvironmentVariable("UNITY_RECEIVE_TIMEOUT", "1");
                Environment.SetEnvironmentVariable("MOTIONPLAY_ENV_FILE", null);
                var viewObject = new GameObject("Test Camera");
                viewObject.transform.SetParent(root.transform);
                var view = viewObject.AddComponent<Camera>();
                view.orthographic = true;
                view.orthographicSize = 3;
                viewObject.transform.position = new Vector3(0, 0, -10);
                var receiverObject = new GameObject("Test Receiver");
                receiverObject.transform.SetParent(root.transform);
                var receiver = receiverObject.AddComponent<UdpReceiver>();
                var cursorObject = new GameObject("Test Cursor");
                cursorObject.transform.SetParent(root.transform);
                var visual = cursorObject.AddComponent<SpriteRenderer>();
                cursorObject.AddComponent<CursorDisc>();
                var cursor = cursorObject.AddComponent<HandCursorController>();
                cursor.Configure(receiver, view);
                root.SetActive(true);
                yield return null;
                Assert.IsFalse(visual.enabled);
                Assert.IsNull(cursor.CurrentPosition);

                Send(sender, port, 0, true);
                yield return WaitFor(() => cursor.IsTracking);
                Assert.IsTrue(visual.enabled);
                Assert.AreEqual(-0.5f * (3 * view.aspect - 0.2f), cursor.CurrentPosition.Value.x, 0.0001f);
                Assert.AreEqual(-1.4f, cursor.CurrentPosition.Value.y, 0.0001f);
                Assert.AreEqual(0, cursor.CurrentPosition.Value.z, 0.0001f);
                Assert.AreEqual(0.12f, visual.bounds.extents.x, 0.0001f);
                Assert.AreEqual(0.12f, visual.bounds.extents.y, 0.0001f);

                Send(sender, port, 1, false);
                yield return WaitFor(() => !cursor.IsTracking);
                Assert.IsFalse(visual.enabled);
                Assert.IsTrue(cursorObject.activeSelf); // Hiding must not disable its own Update.

                Send(sender, port, 2, true);
                yield return WaitFor(() => cursor.IsTracking);
                yield return WaitFor(() => !cursor.IsTracking); // No more packets: actual receiver timeout.
                Assert.IsFalse(visual.enabled);
                Assert.IsNull(cursor.CurrentPosition);

                Send(sender, port, 3, true);
                yield return WaitFor(() => cursor.IsTracking);
                cursor.enabled = false;
                Assert.IsFalse(visual.enabled);
                Assert.IsNull(cursor.CurrentPosition);
                cursor.enabled = true;
                yield return WaitFor(() => cursor.IsTracking);
                receiver.enabled = false;
                yield return null;
                Assert.IsFalse(visual.enabled);
                Assert.IsNull(cursor.CurrentPosition);
            }
            finally
            {
                root.SetActive(false);
                UnityEngine.Object.Destroy(root);
                sender.Dispose();
                foreach (var pair in savedEnvironment) Environment.SetEnvironmentVariable(pair.Key, pair.Value);
            }
        }

        private static IEnumerator WaitFor(Func<bool> predicate)
        {
            float deadline = Time.realtimeSinceStartup + 5;
            while (!predicate() && Time.realtimeSinceStartup < deadline) yield return null;
            Assert.IsTrue(predicate(), "Cursor state did not change before the test deadline.");
        }

        private static void Send(UdpClient sender, int port, long sequence, bool tracking)
        {
            string position = tracking ? "{\"x\":0.25,\"y\":0.75,\"z\":-0.03}" : "null";
            string packet = "{\"type\":\"CV_STATE\",\"version\":1,\"stream_id\":\"a1e111a1-1111-4111-8111-111111111111\"," +
                "\"sequence\":" + sequence + ",\"timestamp\":0,\"hand\":\"right\",\"tracking\":" +
                (tracking ? "true" : "false") + ",\"position\":" + position + ",\"gesture\":\"UNKNOWN\",\"confidence\":" +
                (tracking ? "0.95" : "0") + ",\"mirrored\":true}";
            byte[] bytes = Encoding.UTF8.GetBytes(packet);
            sender.Send(bytes, bytes.Length, "127.0.0.1", port);
        }
    }
}
