using System;
using MotionPlay.Control;
using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>Display fresh palm control on an orthographic camera plane; no gesture-triggered gameplay.</summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(SpriteRenderer))]
    public sealed class HandCursorController : MonoBehaviour
    {
        [SerializeField] private UdpReceiver receiver;
        [SerializeField] private Camera gameplayCamera;
        [SerializeField, Tooltip("Desired final horizontal orientation. Python's mirror flag prevents a second flip.")]
        private bool mirrorControl = true;
        [SerializeField, Min(0.001f)] private float cursorRadius = 0.12f;
        [SerializeField, Min(0)] private float edgeMargin = 0.08f;
        [SerializeField, Min(0.001f)] private float planeDistance = 10f;
        private SpriteRenderer visual;
        private string lastError;

        public Vector3? CurrentPosition { get; private set; }
        public bool IsTracking => CurrentPosition.HasValue;
        public string Status { get; private set; } = "Waiting for tracking";
        public bool MirrorControl => mirrorControl;

        /// <summary>Wire scene references before Play; serialized so the setup survives scene reloads.</summary>
        public void Configure(UdpReceiver source, Camera view)
        {
            receiver = source; gameplayCamera = view; lastError = null;
        }

        private void Awake()
        {
            visual = GetComponent<SpriteRenderer>();
            Hide("Waiting for tracking");
        }

        private void OnEnable()
        {
            if (visual == null) visual = GetComponent<SpriteRenderer>();
            Hide("Waiting for tracking");
        }

        private void Update()
        {
            if (!TryView(out CursorArea area)) return;
            if (!CursorMapper.TryMap(receiver.isActiveAndEnabled ? receiver.Snapshot : null,
                area, mirrorControl, out CursorPoint point))
            {
                Hide("Hand unavailable — cursor hidden");
                return;
            }
            // Camera basis vectors keep mapping correct if the camera is moved
            // or rotated. Model z is not physical depth and does not move the plane.
            Vector3 position = gameplayCamera.transform.position +
                gameplayCamera.transform.right * (float)point.X +
                gameplayCamera.transform.up * (float)point.Y +
                gameplayCamera.transform.forward * planeDistance;
            transform.position = position;
            transform.rotation = gameplayCamera.transform.rotation;
            transform.localScale = Vector3.one * (2 * cursorRadius);
            CurrentPosition = position;
            visual.enabled = true;
            Status = "Tracking " + receiver.CurrentState.Hand;
        }

        private bool TryView(out CursorArea area)
        {
            area = null;
            string error = null;
            if (receiver == null || gameplayCamera == null || visual == null)
                error = "Assign a receiver, camera, and SpriteRenderer to the hand cursor.";
            else if (!gameplayCamera.isActiveAndEnabled || !gameplayCamera.orthographic)
                error = "The hand cursor requires an enabled orthographic camera.";
            else if (visual.sprite == null)
                error = "Assign the cursor disc visual or a one-world-unit sprite.";
            else if (float.IsNaN(planeDistance) || float.IsInfinity(planeDistance) ||
                planeDistance <= gameplayCamera.nearClipPlane || planeDistance >= gameplayCamera.farClipPlane)
                error = "Cursor plane distance must be finite and inside the camera clipping range.";
            else
            {
                try { area = CursorArea.ForOrthographic(gameplayCamera.orthographicSize,
                    gameplayCamera.aspect, cursorRadius, edgeMargin); }
                catch (ArgumentException issue) { error = issue.Message; }
            }
            if (error != null)
            {
                Hide("Cursor configuration error");
                if (lastError != error) Debug.LogError("MotionPlay: " + error, this);
                lastError = error;
                return false;
            }
            lastError = null;
            return true;
        }

        private void Hide(string status)
        {
            CurrentPosition = null;
            if (visual != null) visual.enabled = false;
            Status = status;
        }

        private void OnDisable() => Hide("Cursor disabled");
    }
}
