using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>Small prototype status panel that leaves the cursor view unobstructed.</summary>
    [RequireComponent(typeof(HandCursorController))]
    public sealed class HandCursorStatusPanel : MonoBehaviour
    {
        private HandCursorController cursor;
        private void Awake() => cursor = GetComponent<HandCursorController>();

        private void OnGUI()
        {
            if (cursor == null) return;
            GUILayout.BeginArea(new Rect(16, Screen.height - 66, 560, 50), GUI.skin.box);
            GUILayout.Label("MotionPlay — " + cursor.Status + " | Mirror control: " + cursor.MirrorControl);
            GUILayout.Label("Educational portfolio project. Not a medical device.");
            GUILayout.EndArea();
        }
    }
}
