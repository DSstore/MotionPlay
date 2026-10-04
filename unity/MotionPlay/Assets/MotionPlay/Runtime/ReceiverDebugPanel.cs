using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>Optional numerical diagnostics shared by the receiver and cursor test scenes.</summary>
    [RequireComponent(typeof(UdpReceiver))]
    public sealed class ReceiverDebugPanel : MonoBehaviour
    {
        private UdpReceiver receiver;
        [SerializeField] private bool expanded = true;
        public void SetExpanded(bool value) => expanded = value;
        private void Awake() => receiver = GetComponent<UdpReceiver>();

        private void OnGUI()
        {
            if (receiver == null) return;
            GUILayout.BeginArea(new Rect(16, 16, 560, expanded ? 320 : 105), GUI.skin.box);
            GUILayout.Label("MotionPlay — UDP receiver");
            GUILayout.Label(receiver.Status);
            if (GUILayout.Button(expanded ? "Collapse diagnostics" : "Expand diagnostics")) expanded = !expanded;
            if (!expanded) { GUILayout.EndArea(); return; }
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
