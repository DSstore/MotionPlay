using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>Temporary numeric diagnostics; no cursor movement or gameplay.</summary>
    [RequireComponent(typeof(UdpReceiver))]
    public sealed class ReceiverDebugPanel : MonoBehaviour
    {
        private UdpReceiver receiver;
        private void Awake() => receiver = GetComponent<UdpReceiver>();

        private void OnGUI()
        {
            if (receiver == null) return;
            GUILayout.BeginArea(new Rect(16, 16, 560, 320), GUI.skin.box);
            GUILayout.Label("MotionPlay — Phase 6 UDP receiver");
            GUILayout.Label(receiver.Status);
            var snapshot = receiver.Snapshot;
            if (snapshot == null)
                GUILayout.Label("Waiting for listener startup.");
            else
            {
                GUILayout.Label("Accepted: " + snapshot.Accepted + "   Invalid: " + snapshot.Invalid +
                                "   Rejected: " + snapshot.Rejected);
                var state = snapshot.State;
                if (state == null)
                    GUILayout.Label(snapshot.Accepted == 0 ? "Waiting for first valid packet." :
                                    "Receive timeout — tracking unavailable.");
                else
                {
                    GUILayout.Label("Stream: " + state.StreamId);
                    GUILayout.Label("Sequence: " + state.Sequence + "   Hand: " + state.Hand);
                    GUILayout.Label("Tracking: " + state.Tracking + "   Gesture: " + state.Gesture +
                                    "   Mirrored: " + state.Mirrored);
                    if (state.Position != null)
                        GUILayout.Label(string.Format("Palm: x={0:F3}  y={1:F3}  z={2:F3}   Confidence={3:F3}",
                            state.Position.X, state.Position.Y, state.Position.Z, state.Confidence));
                    else GUILayout.Label("No active palm position.");
                }
                GUILayout.Label(string.Format("Worker → latest Update delay: {0:F2} ms", receiver.LastApplyDelayMs));
            }
            GUILayout.Label("Educational portfolio project. Not a medical device.");
            GUILayout.EndArea();
        }
    }
}
