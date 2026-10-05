using System;
using MotionPlay.Games;
using MotionPlay.Networking;
using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>
    /// Reach Garden prototype: hold the hand cursor on each target to water it. Runs the engine-independent
    /// <see cref="ReachGardenGame"/> and draws original geometric placeholders (no artwork).
    /// </summary>
    [DefaultExecutionOrder(10)] // Run after HandCursorController so the game reads this frame's position.
    [DisallowMultipleComponent]
    public sealed class ReachGardenController : MonoBehaviour
    {
        [SerializeField] private HandCursorController cursor;
        [SerializeField] private Camera gameplayCamera;
        [SerializeField, Min(0.1f)] private float targetRadius = 0.5f;
        [SerializeField, Min(0.1f)] private float dwellSeconds = 0.8f;
        [SerializeField, Min(1f)] private float targetTimeoutSeconds = 8f;
        [SerializeField, Min(1)] private int targetCount = 8;
        [SerializeField, Min(0)] private float edgeMargin = 0.15f;
        [SerializeField, Min(0.001f)] private float planeDistance = 10f;

        private static readonly Color Dry = new Color(0.55f, 0.42f, 0.22f, 0.85f);
        private static readonly Color Growing = new Color(0.95f, 0.85f, 0.3f, 1f);
        private static readonly Color Bloomed = new Color(0.45f, 0.95f, 0.5f, 1f);
        private static readonly Color RestartRing = new Color(0.35f, 0.5f, 0.75f, 0.85f);

        private ReachGardenGame game;
        private Texture2D texture;
        private Sprite sprite;
        private SpriteRenderer baseRenderer;
        private SpriteRenderer fillRenderer;
        private string lastError;
        private ResultSender sender;
        private ReachGardenPhase lastPhase = ReachGardenPhase.WaitingForHand;
        private string sessionId;
        private string sessionHand;
        private long sessionStartedAt;

        public ReachGardenGame Game => game;

        /// <summary>Wire scene references before Play; serialized so the setup survives scene reloads.</summary>
        public void Configure(HandCursorController handCursor, Camera view)
        {
            cursor = handCursor; gameplayCamera = view; lastError = null;
        }

        private void Awake()
        {
            BuildVisuals();
            sender = GetComponent<ResultSender>();
            if (sender == null) sender = gameObject.AddComponent<ResultSender>();
            try
            {
                var settings = new ReachGardenSettings
                {
                    TargetCount = targetCount,
                    TargetRadius = targetRadius,
                    DwellSeconds = dwellSeconds,
                    TargetTimeoutSeconds = targetTimeoutSeconds
                };
                game = new ReachGardenGame(settings, 1, 1, Environment.TickCount);
            }
            catch (ArgumentException issue)
            {
                Debug.LogError("MotionPlay Reach Garden settings are invalid: " + issue.Message, this);
                enabled = false;
            }
        }

        private void Update()
        {
            if (game == null) return;
            if (!TryBounds(out double halfWidth, out double halfHeight)) { SetTargetVisible(false); return; }
            game.SetBounds(halfWidth, halfHeight);

            bool restartPressed = Input.GetKeyDown(KeyCode.R);
            if (restartPressed) game.Restart();

            bool tracking = cursor != null && cursor.isActiveAndEnabled && cursor.IsTracking;
            double x = 0, y = 0;
            if (tracking)
            {
                Vector3 local = gameplayCamera.transform.InverseTransformPoint(cursor.CurrentPosition.Value);
                x = local.x; y = local.y;
            }
            game.Step(Time.deltaTime, tracking, x, y);
            TrackSession(restartPressed);
            Render();
        }

        /// <summary>Open a session when a round starts and send its result when the round completes.</summary>
        private void TrackSession(bool restartPressed)
        {
            ReachGardenPhase phase = game.Phase;
            if (phase == ReachGardenPhase.Playing)
            {
                if (lastPhase != ReachGardenPhase.Playing || restartPressed)
                {
                    sessionId = Guid.NewGuid().ToString("D");
                    sessionStartedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    sessionHand = null;
                }
                if (cursor != null && cursor.CurrentHand != null) sessionHand = cursor.CurrentHand;
            }
            else if (phase == ReachGardenPhase.Complete && lastPhase == ReachGardenPhase.Playing)
            {
                if (sessionHand == null)
                    Debug.LogWarning("MotionPlay: round finished without a known hand; result not sent.", this);
                else
                    sender.Submit(SessionResult.FromStats(game.Stats, "reach_garden", sessionHand, "default",
                        sessionId, sessionStartedAt, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
            }
            lastPhase = phase;
        }

        private bool TryBounds(out double halfWidth, out double halfHeight)
        {
            halfWidth = halfHeight = 0;
            string error = null;
            if (cursor == null || gameplayCamera == null)
                error = "Assign the hand cursor and camera to Reach Garden.";
            else if (!gameplayCamera.isActiveAndEnabled || !gameplayCamera.orthographic)
                error = "Reach Garden requires an enabled orthographic camera.";
            else
            {
                double inset = targetRadius + edgeMargin;
                halfHeight = gameplayCamera.orthographicSize - inset;
                halfWidth = gameplayCamera.orthographicSize * gameplayCamera.aspect - inset;
                if (!(halfWidth > 0) || !(halfHeight > 0))
                    error = "The camera view is too small for the target radius and margin.";
            }
            if (error != null)
            {
                if (lastError != error) Debug.LogError("MotionPlay: " + error, this);
                lastError = error;
                return false;
            }
            lastError = null;
            return true;
        }

        private void Render()
        {
            bool waiting = game.Phase == ReachGardenPhase.WaitingForHand;
            SetTargetVisible(!waiting);
            if (waiting) return;

            Vector3 position = gameplayCamera.transform.position +
                gameplayCamera.transform.right * (float)game.TargetX +
                gameplayCamera.transform.up * (float)game.TargetY +
                gameplayCamera.transform.forward * planeDistance;
            transform.SetPositionAndRotation(position, gameplayCamera.transform.rotation);

            float progress = (float)game.DwellProgress;
            bool complete = game.Phase == ReachGardenPhase.Complete;
            baseRenderer.transform.localScale = Vector3.one * (2 * targetRadius);
            baseRenderer.color = complete ? RestartRing : Dry;
            // The fill grows from the center as the dwell progresses and warms toward green.
            fillRenderer.transform.localScale = Vector3.one * (2 * targetRadius * progress);
            fillRenderer.color = Color.Lerp(Growing, Bloomed, progress);
        }

        private void SetTargetVisible(bool visible)
        {
            if (baseRenderer != null) baseRenderer.enabled = visible;
            if (fillRenderer != null) fillRenderer.enabled = visible;
        }

        private void BuildVisuals()
        {
            const int size = 64;
            texture = new Texture2D(size, size, TextureFormat.RGBA32, false)
            { name = "MotionPlay garden disc", filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp };
            var pixels = new Color32[size * size];
            for (int py = 0; py < size; py++)
                for (int px = 0; px < size; px++)
                {
                    float dx = (px + 0.5f - size / 2f) / (size / 2f);
                    float dy = (py + 0.5f - size / 2f) / (size / 2f);
                    float radius = Mathf.Sqrt(dx * dx + dy * dy);
                    pixels[py * size + px] = new Color32(255, 255, 255, (byte)(255 * Mathf.Clamp01((1 - radius) * size / 2f)));
                }
            texture.SetPixels32(pixels);
            texture.Apply(false);
            sprite = Sprite.Create(texture, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), size, 0, SpriteMeshType.FullRect);
            sprite.name = "MotionPlay garden disc";

            baseRenderer = MakeDisc("Target Base", 10);
            fillRenderer = MakeDisc("Target Fill", 11);
            SetTargetVisible(false);
        }

        private SpriteRenderer MakeDisc(string objectName, int order)
        {
            var child = new GameObject(objectName);
            child.transform.SetParent(transform, false);
            var renderer = child.AddComponent<SpriteRenderer>();
            renderer.sprite = sprite;
            renderer.sortingOrder = order; // Below the hand cursor, which uses order 100.
            return renderer;
        }

        private void OnGUI()
        {
            if (game == null) return;
            GUILayout.BeginArea(new Rect(Screen.width - 316, 16, 300, game.Phase == ReachGardenPhase.Complete ? 240 : 110), GUI.skin.box);
            GUILayout.Label("MotionPlay — Reach Garden");
            switch (game.Phase)
            {
                case ReachGardenPhase.WaitingForHand:
                    GUILayout.Label("Show your hand to begin.");
                    break;
                case ReachGardenPhase.Playing:
                    GUILayout.Label("Flower " + (game.TargetIndex + 1) + " of " + game.TargetCount +
                        "  |  Watered " + game.TargetsWatered + "  Missed " + game.TargetsMissed);
                    GUILayout.Label("Hold the cursor on the flower. Time left: " + game.TimeRemaining.ToString("0.0") + " s");
                    break;
                default:
                    GUILayout.Label("Round complete: watered " + game.TargetsWatered + " of " + game.TargetCount + ".");
                    ReachGardenStats stats = game.Stats;
                    GUILayout.Label("Accuracy " + Percent(stats.Accuracy) + "  |  Best streak " + stats.BestStreak);
                    GUILayout.Label("Reaction " + Seconds(stats.AverageReactionTime) + "  Movement " + Seconds(stats.AverageMovementTime));
                    GUILayout.Label("Hold stability " + Percent(stats.AverageHoldStability) + "  Path efficiency " + Percent(stats.AveragePathEfficiency));
                    GUILayout.Label("Time " + stats.DurationSeconds.ToString("0.0") + " s  |  " + DeliveryText());
                    GUILayout.Label("Hold the cursor on the blue circle (or press R) to play again.");
                    break;
            }
            GUILayout.EndArea();
        }

        private string DeliveryText()
        {
            if (sender == null || sender.Error != null) return "Result not sent";
            switch (sender.State)
            {
                case DeliveryState.Sending: return "Saving result (try " + sender.Attempts + ")";
                case DeliveryState.Confirmed: return "Result saved";
                case DeliveryState.Rejected: return "Result rejected";
                case DeliveryState.NotConfirmed: return "Result NOT saved (receiver off?)";
                default: return "Result not sent";
            }
        }

        private static string Percent(double? value) => value.HasValue ? (value.Value * 100).ToString("0") + "%" : "-";
        private static string Seconds(double? value) => value.HasValue ? value.Value.ToString("0.00") + " s" : "-";

        private void OnDestroy()
        {
            if (sprite != null) Destroy(sprite);
            if (texture != null) Destroy(texture);
        }
    }
}
