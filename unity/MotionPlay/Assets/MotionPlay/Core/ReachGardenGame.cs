using System;

namespace MotionPlay.Games
{
    public enum ReachGardenPhase { WaitingForHand, Playing, Complete }

    /// <summary>Tunable Reach Garden rules. Distances are camera-plane world units, times are seconds.</summary>
    public sealed class ReachGardenSettings
    {
        public int TargetCount { get; set; } = 8;
        public double TargetRadius { get; set; } = 0.5;
        /// <summary>Time the cursor must stay inside a target to water it.</summary>
        public double DwellSeconds { get; set; } = 0.8;
        /// <summary>Tracked time allowed per target; the timer pauses while the hand is lost.</summary>
        public double TargetTimeoutSeconds { get; set; } = 8;
        /// <summary>Minimum distance between consecutive targets so each one needs a real reach.</summary>
        public double MinTargetSeparation { get; set; } = 1.5;
        /// <summary>Dwell progress drains this many times faster than it fills when the cursor leaves.</summary>
        public double DwellDecayFactor { get; set; } = 1.5;

        internal void Validate()
        {
            if (TargetCount < 1) throw new ArgumentException("TargetCount must be at least 1.");
            if (!Positive(TargetRadius)) throw new ArgumentException("TargetRadius must be finite and positive.");
            if (!Positive(DwellSeconds)) throw new ArgumentException("DwellSeconds must be finite and positive.");
            if (!Positive(TargetTimeoutSeconds) || TargetTimeoutSeconds <= DwellSeconds)
                throw new ArgumentException("TargetTimeoutSeconds must be finite and longer than DwellSeconds.");
            if (double.IsNaN(MinTargetSeparation) || double.IsInfinity(MinTargetSeparation) || MinTargetSeparation < 0)
                throw new ArgumentException("MinTargetSeparation must be finite and nonnegative.");
            if (!Positive(DwellDecayFactor)) throw new ArgumentException("DwellDecayFactor must be finite and positive.");
        }

        private static bool Positive(double value) => !double.IsNaN(value) && !double.IsInfinity(value) && value > 0;
    }

    /// <summary>
    /// Reach Garden rules: hold the cursor on each target to water it. Contains no engine types so
    /// the same code runs in Unity and in the standalone test harness. It tracks only what the
    /// current round needs; session statistics are a later phase.
    /// </summary>
    public sealed class ReachGardenGame
    {
        /// <summary>Largest time step accepted, so a frame hitch cannot complete a target.</summary>
        public const double MaxStepSeconds = 0.1;

        private readonly ReachGardenSettings settings;
        private readonly Random random;
        private double halfWidth;
        private double halfHeight;
        private double dwell;
        private bool restartArmed;

        public ReachGardenGame(ReachGardenSettings settings, double boundsHalfWidth, double boundsHalfHeight, int seed)
        {
            this.settings = settings ?? throw new ArgumentNullException(nameof(settings));
            settings.Validate();
            random = new Random(seed);
            SetBounds(boundsHalfWidth, boundsHalfHeight);
            Phase = ReachGardenPhase.WaitingForHand;
        }

        public ReachGardenPhase Phase { get; private set; }
        public double TargetX { get; private set; }
        public double TargetY { get; private set; }
        public double TargetRadius => settings.TargetRadius;
        /// <summary>Zero-based index of the active target; equals TargetCount when complete.</summary>
        public int TargetIndex { get; private set; }
        public int TargetCount => settings.TargetCount;
        public int TargetsWatered { get; private set; }
        public int TargetsMissed { get; private set; }
        public double TimeRemaining { get; private set; }
        /// <summary>Fraction (0 to 1) of the dwell completed on the active target.</summary>
        public double DwellProgress => Math.Min(1, dwell / settings.DwellSeconds);

        /// <summary>Update the area in which target centers may be placed (for example after a view resize).</summary>
        public void SetBounds(double boundsHalfWidth, double boundsHalfHeight)
        {
            if (!Valid(boundsHalfWidth) || !Valid(boundsHalfHeight))
                throw new ArgumentException("Target bounds must be finite and positive.");
            halfWidth = boundsHalfWidth;
            halfHeight = boundsHalfHeight;
            if (Phase == ReachGardenPhase.Playing)
            {
                TargetX = Math.Max(-halfWidth, Math.Min(halfWidth, TargetX));
                TargetY = Math.Max(-halfHeight, Math.Min(halfHeight, TargetY));
            }
        }

        /// <summary>Advance by one frame. Cursor coordinates are ignored unless <paramref name="tracking"/> is true.</summary>
        public void Step(double deltaSeconds, bool tracking, double cursorX, double cursorY)
        {
            if (double.IsNaN(deltaSeconds) || double.IsInfinity(deltaSeconds) || deltaSeconds < 0) return;
            double dt = Math.Min(deltaSeconds, MaxStepSeconds);
            if (tracking && (double.IsNaN(cursorX) || double.IsInfinity(cursorX) ||
                             double.IsNaN(cursorY) || double.IsInfinity(cursorY))) tracking = false;

            if (Phase == ReachGardenPhase.WaitingForHand)
            {
                if (tracking) StartRound();
                return;
            }

            bool inside = tracking && Inside(cursorX, cursorY);
            if (inside) dwell += dt;
            else dwell = Math.Max(0, dwell - dt * settings.DwellDecayFactor);

            if (Phase == ReachGardenPhase.Complete)
            {
                // The restart target sits mid-view; leave it once so a cursor left there cannot restart instantly.
                if (tracking && !inside) restartArmed = true;
                if (!restartArmed) dwell = 0;
                else if (dwell >= settings.DwellSeconds) StartRound();
                return;
            }

            if (tracking) TimeRemaining = Math.Max(0, TimeRemaining - dt);
            if (dwell >= settings.DwellSeconds) { TargetsWatered++; Advance(); }
            else if (TimeRemaining <= 0) { TargetsMissed++; Advance(); }
        }

        /// <summary>Begin a fresh round immediately, for example from a keyboard shortcut.</summary>
        public void Restart() => StartRound();

        private void StartRound()
        {
            TargetsWatered = 0;
            TargetsMissed = 0;
            TargetIndex = 0;
            Phase = ReachGardenPhase.Playing;
            PlaceTarget();
        }

        private void Advance()
        {
            dwell = 0;
            TargetIndex++;
            if (TargetsWatered + TargetsMissed >= settings.TargetCount)
            {
                Phase = ReachGardenPhase.Complete;
                TargetIndex = settings.TargetCount;
                TargetX = 0; TargetY = 0;
                TimeRemaining = 0;
                restartArmed = false;
                return;
            }
            PlaceTarget();
        }

        private void PlaceTarget()
        {
            double previousX = TargetX, previousY = TargetY;
            bool first = TargetIndex == 0;
            double x = 0, y = 0;
            for (int attempt = 0; attempt < 30; attempt++)
            {
                x = (random.NextDouble() * 2 - 1) * halfWidth;
                y = (random.NextDouble() * 2 - 1) * halfHeight;
                double dx = x - previousX, dy = y - previousY;
                if (first || Math.Sqrt(dx * dx + dy * dy) >= settings.MinTargetSeparation) break;
            }
            TargetX = x; TargetY = y;
            dwell = 0;
            TimeRemaining = settings.TargetTimeoutSeconds;
        }

        private bool Inside(double x, double y)
        {
            double dx = x - TargetX, dy = y - TargetY;
            return dx * dx + dy * dy <= settings.TargetRadius * settings.TargetRadius;
        }

        private static bool Valid(double value) => !double.IsNaN(value) && !double.IsInfinity(value) && value > 0;
    }
}
