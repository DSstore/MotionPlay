using System;

namespace MotionPlay.Games
{
    /// <summary>What the adapter decided after a finished round.</summary>
    public enum DifficultyChange { None, Harder, Easier }

    /// <summary>
    /// Adaptive difficulty for Reach Garden. Five levels map to fixed rule presets; after each finished
    /// round the level moves by at most one step, and only after two qualifying rounds in a row so a single
    /// lucky or unlucky round does not swing it. Contains no engine types so the standalone harness tests it.
    /// These are gameplay-tuning heuristics for a portfolio project, not a clinical assessment.
    /// </summary>
    public sealed class ReachGardenDifficulty
    {
        public const int MinLevel = 1;
        public const int MaxLevel = 5;
        public const int DefaultLevel = 3;

        /// <summary>Accuracy at or above this (with steady holds) counts as a round that was too easy.</summary>
        public const double HarderAccuracy = 0.9;
        /// <summary>Hold stability needed alongside <see cref="HarderAccuracy"/>.</summary>
        public const double HarderStability = 0.8;
        /// <summary>Accuracy at or below this counts as a round that was too hard.</summary>
        public const double EasierAccuracy = 0.5;
        /// <summary>Qualifying rounds in a row required before the level moves.</summary>
        public const int RoundsToChange = 2;
        /// <summary>Rounds with fewer finished targets than this are ignored.</summary>
        public const int MinAttempted = 4;

        private int easyStreak;
        private int hardStreak;

        public ReachGardenDifficulty(int level = DefaultLevel)
        {
            Level = Clamp(level);
        }

        public int Level { get; private set; }
        /// <summary>Label sent with each result (fits the protocol's 32-character limit), e.g. <c>level_3</c>.</summary>
        public string Label => LabelFor(Level);

        public static string LabelFor(int level) => "level_" + Clamp(level);

        /// <summary>Parse a label such as <c>level_4</c>; anything else (including the old <c>default</c>) gives null.</summary>
        public static int? ParseLabel(string label)
        {
            const string prefix = "level_";
            if (label == null || !label.StartsWith(prefix, StringComparison.Ordinal)) return null;
            int level;
            if (!int.TryParse(label.Substring(prefix.Length), System.Globalization.NumberStyles.None,
                    System.Globalization.CultureInfo.InvariantCulture, out level)) return null;
            return level >= MinLevel && level <= MaxLevel ? (int?)level : null;
        }

        /// <summary>Rules for a level; <paramref name="targetCount"/> is not part of difficulty and is passed through.</summary>
        public static ReachGardenSettings SettingsFor(int level, int targetCount = 8)
        {
            var settings = new ReachGardenSettings { TargetCount = targetCount };
            switch (Clamp(level))
            {
                case 1: settings.TargetRadius = 0.7; settings.DwellSeconds = 0.5;  settings.TargetTimeoutSeconds = 10;  settings.MinTargetSeparation = 1.0; break;
                case 2: settings.TargetRadius = 0.6; settings.DwellSeconds = 0.65; settings.TargetTimeoutSeconds = 9;   settings.MinTargetSeparation = 1.25; break;
                case 3: settings.TargetRadius = 0.5; settings.DwellSeconds = 0.8;  settings.TargetTimeoutSeconds = 8;   settings.MinTargetSeparation = 1.5; break;
                case 4: settings.TargetRadius = 0.4; settings.DwellSeconds = 1.0;  settings.TargetTimeoutSeconds = 6.5; settings.MinTargetSeparation = 1.85; break;
                default: settings.TargetRadius = 0.3; settings.DwellSeconds = 1.2; settings.TargetTimeoutSeconds = 5;   settings.MinTargetSeparation = 2.2; break;
            }
            return settings;
        }

        /// <summary>Set the level directly (for example a manual override) and forget any partial streak.</summary>
        public void SetLevel(int level)
        {
            Level = Clamp(level);
            easyStreak = 0;
            hardStreak = 0;
        }

        /// <summary>Judge a finished round and possibly move the level by one step.</summary>
        public DifficultyChange RecordRound(ReachGardenStats stats)
        {
            if (stats == null) throw new ArgumentNullException(nameof(stats));
            double? accuracy = stats.Accuracy;
            if (stats.Attempted < MinAttempted || !accuracy.HasValue) return DifficultyChange.None;

            double? stability = stats.AverageHoldStability;
            bool tooEasy = accuracy.Value >= HarderAccuracy && stability.HasValue && stability.Value >= HarderStability;
            bool tooHard = accuracy.Value <= EasierAccuracy;

            easyStreak = tooEasy ? easyStreak + 1 : 0;
            hardStreak = tooHard ? hardStreak + 1 : 0;

            if (easyStreak >= RoundsToChange)
            {
                easyStreak = 0;
                if (Level < MaxLevel) { Level++; return DifficultyChange.Harder; }
            }
            else if (hardStreak >= RoundsToChange)
            {
                hardStreak = 0;
                if (Level > MinLevel) { Level--; return DifficultyChange.Easier; }
            }
            return DifficultyChange.None;
        }

        private static int Clamp(int level) => Math.Max(MinLevel, Math.Min(MaxLevel, level));
    }
}
