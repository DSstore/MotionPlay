using System;

namespace MotionPlay.Games
{
    /// <summary>
    /// Session statistics for one Reach Garden round. Times are seconds of tracked hand time, distances
    /// are camera-plane world units, ratios are 0 to 1. A metric with no samples is null, never a
    /// fabricated zero. These are gameplay measurements only, with no medical interpretation.
    ///
    /// Definitions (per flower, then averaged over the flowers that qualify):
    ///   reaction time   tracked time from the flower appearing until the cursor first moves
    ///                   <see cref="OnsetDistance"/> from where it started (or enters the flower, if sooner).
    ///   movement time   tracked time from that onset until the cursor first enters the flower.
    ///   hold stability  share of the tracked time since first entry that the cursor stayed inside.
    ///   path efficiency straight-line distance to the entry point divided by the distance the cursor
    ///                   actually travelled before entering; skipped if tracking was lost on the way or
    ///                   the cursor began inside the flower.
    ///   accuracy        flowers watered divided by flowers attempted (watered plus missed).
    /// Reaction, movement, stability, and efficiency use every flower the cursor entered, watered or not.
    /// </summary>
    public sealed class ReachGardenStats
    {
        /// <summary>Cursor travel that counts as starting to move toward a flower.</summary>
        public const double OnsetDistance = 0.1;

        // Per-flower state.
        private double trackedTime, pathLength, startX, startY, lastX, lastY;
        private double entryTime, entryPath, entryX, entryY, insideTime, sinceEntry;
        private double onsetTime;
        private bool started, hasLast, interrupted, hasOnset, entered;

        // Round totals.
        private double reactionSum, movementSum, stabilitySum, efficiencySum;
        private int enteredCount, efficiencyCount;

        public int Attempted { get; private set; }
        public int Watered { get; private set; }
        public int Score => Watered;
        public int CurrentStreak { get; private set; }
        public int BestStreak { get; private set; }
        /// <summary>Seconds of play since the round began, including time the hand was lost.</summary>
        public double DurationSeconds { get; private set; }

        public double? Accuracy => Attempted > 0 ? (double?)((double)Watered / Attempted) : null;
        public double? AverageReactionTime => enteredCount > 0 ? (double?)(reactionSum / enteredCount) : null;
        public double? AverageMovementTime => enteredCount > 0 ? (double?)(movementSum / enteredCount) : null;
        public double? AverageHoldStability => enteredCount > 0 ? (double?)(stabilitySum / enteredCount) : null;
        public double? AveragePathEfficiency => efficiencyCount > 0 ? (double?)(efficiencySum / efficiencyCount) : null;

        internal void Reset()
        {
            Attempted = Watered = CurrentStreak = BestStreak = 0;
            DurationSeconds = 0;
            reactionSum = movementSum = stabilitySum = efficiencySum = 0;
            enteredCount = efficiencyCount = 0;
            BeginTarget();
        }

        internal void BeginTarget()
        {
            trackedTime = pathLength = startX = startY = lastX = lastY = 0;
            entryTime = entryPath = entryX = entryY = insideTime = sinceEntry = onsetTime = 0;
            started = hasLast = interrupted = hasOnset = entered = false;
        }

        /// <summary>Record one frame of play on the active flower. Cursor values are used only while tracking.</summary>
        internal void Observe(double dt, bool tracking, double x, double y, bool inside)
        {
            DurationSeconds += dt;
            if (!tracking)
            {
                if (hasLast && !entered) interrupted = true;
                hasLast = false;
                return;
            }

            trackedTime += dt;
            if (!started) { started = true; startX = x; startY = y; }
            if (hasLast) pathLength += Distance(lastX, lastY, x, y);
            hasLast = true; lastX = x; lastY = y;

            if (!hasOnset && Distance(startX, startY, x, y) >= OnsetDistance)
            {
                hasOnset = true; onsetTime = trackedTime;
            }
            if (!entered && inside)
            {
                entered = true; entryTime = trackedTime; entryPath = pathLength; entryX = x; entryY = y;
                if (!hasOnset) { hasOnset = true; onsetTime = trackedTime; }
            }
            if (entered)
            {
                sinceEntry += dt;
                if (inside) insideTime += dt;
            }
        }

        /// <summary>Close out the active flower as watered or missed.</summary>
        internal void EndTarget(bool watered)
        {
            Attempted++;
            if (watered)
            {
                Watered++;
                CurrentStreak++;
                BestStreak = Math.Max(BestStreak, CurrentStreak);
            }
            else CurrentStreak = 0;

            if (!entered) return;
            enteredCount++;
            reactionSum += onsetTime;
            movementSum += entryTime - onsetTime;
            stabilitySum += sinceEntry > 0 ? Math.Min(1, insideTime / sinceEntry) : 1;
            if (!interrupted && entryPath > 1e-9)
            {
                efficiencySum += Math.Min(1, Distance(startX, startY, entryX, entryY) / entryPath);
                efficiencyCount++;
            }
        }

        private static double Distance(double ax, double ay, double bx, double by)
        {
            double dx = bx - ax, dy = by - ay;
            return Math.Sqrt(dx * dx + dy * dy);
        }
    }
}
