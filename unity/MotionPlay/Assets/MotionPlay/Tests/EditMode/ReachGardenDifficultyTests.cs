using System;
using MotionPlay.Games;
using NUnit.Framework;

namespace MotionPlay.Tests
{
    public sealed class ReachGardenDifficultyTests
    {
        private const double Frame = 1.0 / 30;

        private static ReachGardenGame NewGame(int level = 3)
        {
            var game = new ReachGardenGame(ReachGardenDifficulty.SettingsFor(level), 3.0, 2.0, 11);
            game.Step(Frame, true, 0, 0);
            return game;
        }

        private static void Water(ReachGardenGame game)
        {
            int attempted = game.Stats.Attempted;
            double tx = game.TargetX, ty = game.TargetY;
            game.Step(Frame, true, tx - 2, ty);
            for (int i = 1; i <= 20; i++) game.Step(Frame, true, tx - 2 + 2.0 * i / 20, ty);
            for (int i = 0; i < 200 && game.Stats.Attempted == attempted; i++) game.Step(Frame, true, tx, ty);
        }

        private static void Miss(ReachGardenGame game)
        {
            int attempted = game.Stats.Attempted;
            double tx = game.TargetX, ty = game.TargetY;
            for (int i = 0; i < 1000 && game.Stats.Attempted == attempted; i++) game.Step(Frame, true, tx - 2, ty);
        }

        /// <summary>Play (or replay) a full round with the given number of watered flowers, ending Complete.</summary>
        private static ReachGardenStats Round(ReachGardenGame game, int watered)
        {
            if (game.Phase == ReachGardenPhase.Complete) game.Restart();
            for (int i = 0; i < game.TargetCount; i++)
            {
                if (i < watered) Water(game); else Miss(game);
            }
            Assert.AreEqual(ReachGardenPhase.Complete, game.Phase);
            return game.Stats;
        }

        [Test]
        public void EveryLevelPresetIsValidAndGetsStrictlyHarder()
        {
            ReachGardenSettings previous = null;
            for (int level = ReachGardenDifficulty.MinLevel; level <= ReachGardenDifficulty.MaxLevel; level++)
            {
                ReachGardenSettings s = ReachGardenDifficulty.SettingsFor(level, 6);
                Assert.DoesNotThrow(() => new ReachGardenGame(s, 3, 2, 1));
                Assert.AreEqual(6, s.TargetCount);
                if (previous != null)
                {
                    Assert.Less(s.TargetRadius, previous.TargetRadius);
                    Assert.Greater(s.DwellSeconds, previous.DwellSeconds);
                    Assert.Less(s.TargetTimeoutSeconds, previous.TargetTimeoutSeconds);
                    Assert.Greater(s.MinTargetSeparation, previous.MinTargetSeparation);
                }
                previous = s;
            }
        }

        [Test]
        public void MiddleLevelMatchesTheOriginalDefaults()
        {
            ReachGardenSettings preset = ReachGardenDifficulty.SettingsFor(ReachGardenDifficulty.DefaultLevel);
            var original = new ReachGardenSettings();
            Assert.AreEqual(original.TargetRadius, preset.TargetRadius);
            Assert.AreEqual(original.DwellSeconds, preset.DwellSeconds);
            Assert.AreEqual(original.TargetTimeoutSeconds, preset.TargetTimeoutSeconds);
            Assert.AreEqual(original.MinTargetSeparation, preset.MinTargetSeparation);
            Assert.AreEqual(original.TargetCount, preset.TargetCount);
        }

        [Test]
        public void LevelsAreClampedAndLabelled()
        {
            Assert.AreEqual(1, new ReachGardenDifficulty(-4).Level);
            Assert.AreEqual(5, new ReachGardenDifficulty(99).Level);
            Assert.AreEqual(3, new ReachGardenDifficulty().Level);
            Assert.AreEqual("level_4", new ReachGardenDifficulty(4).Label);
            Assert.AreEqual("level_1", ReachGardenDifficulty.LabelFor(0));
            Assert.LessOrEqual(ReachGardenDifficulty.LabelFor(5).Length, 32);
        }

        [Test]
        public void LabelsParseBackAndLegacyOnesAreUnknown()
        {
            for (int level = 1; level <= 5; level++)
                Assert.AreEqual(level, ReachGardenDifficulty.ParseLabel(ReachGardenDifficulty.LabelFor(level)));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("default"));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel(null));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("level_0"));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("level_6"));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("level_-2"));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("level_"));
            Assert.IsNull(ReachGardenDifficulty.ParseLabel("Level_3"));
        }

        [Test]
        public void OneEasyRoundDoesNotChangeTheLevelButTwoDo()
        {
            ReachGardenGame game = NewGame();
            var difficulty = new ReachGardenDifficulty(3);
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(Round(game, 8)));
            Assert.AreEqual(3, difficulty.Level);
            Assert.AreEqual(DifficultyChange.Harder, difficulty.RecordRound(Round(game, 8)));
            Assert.AreEqual(4, difficulty.Level);
        }

        [Test]
        public void TwoHardRoundsMakeItEasier()
        {
            ReachGardenGame game = NewGame();
            var difficulty = new ReachGardenDifficulty(3);
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(Round(game, 4)));
            Assert.AreEqual(DifficultyChange.Easier, difficulty.RecordRound(Round(game, 2)));
            Assert.AreEqual(2, difficulty.Level);
        }

        [Test]
        public void AMiddlingRoundBreaksTheStreak()
        {
            ReachGardenGame game = NewGame();
            var difficulty = new ReachGardenDifficulty(3);
            difficulty.RecordRound(Round(game, 8));
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(Round(game, 6)));
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(Round(game, 8)));
            Assert.AreEqual(3, difficulty.Level);
        }

        [Test]
        public void ChangesStopAtTheEnds()
        {
            ReachGardenGame game = NewGame();
            var top = new ReachGardenDifficulty(ReachGardenDifficulty.MaxLevel);
            top.RecordRound(Round(game, 8));
            Assert.AreEqual(DifficultyChange.None, top.RecordRound(Round(game, 8)));
            Assert.AreEqual(ReachGardenDifficulty.MaxLevel, top.Level);

            var bottom = new ReachGardenDifficulty(ReachGardenDifficulty.MinLevel);
            bottom.RecordRound(Round(game, 0));
            Assert.AreEqual(DifficultyChange.None, bottom.RecordRound(Round(game, 0)));
            Assert.AreEqual(ReachGardenDifficulty.MinLevel, bottom.Level);
        }

        [Test]
        public void SetLevelClearsAPartialStreak()
        {
            ReachGardenGame game = NewGame();
            var difficulty = new ReachGardenDifficulty(3);
            difficulty.RecordRound(Round(game, 8));
            difficulty.SetLevel(3);
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(Round(game, 8)));
            Assert.AreEqual(3, difficulty.Level);
        }

        [Test]
        public void RoundsWithNoDataAreIgnored()
        {
            var difficulty = new ReachGardenDifficulty(3);
            Assert.AreEqual(DifficultyChange.None, difficulty.RecordRound(new ReachGardenStats()));
            Assert.Throws<ArgumentNullException>(() => difficulty.RecordRound(null));
        }

        [Test]
        public void ApplySettingsIsRefusedMidRoundAndAppliedBetweenRounds()
        {
            ReachGardenGame game = NewGame(3);
            Assert.AreEqual(ReachGardenPhase.Playing, game.Phase);
            Assert.IsFalse(game.ApplySettings(ReachGardenDifficulty.SettingsFor(5)));
            Assert.AreEqual(0.5, game.TargetRadius);

            Round(game, 8);
            Assert.IsTrue(game.ApplySettings(ReachGardenDifficulty.SettingsFor(5)));
            Assert.AreEqual(0.3, game.TargetRadius);
            game.Restart();
            Assert.AreEqual(0.3, game.TargetRadius);
            Assert.AreEqual(5.0, game.TimeRemaining, 1e-9);
        }

        [Test]
        public void ApplySettingsRejectsInvalidInput()
        {
            ReachGardenGame game = new ReachGardenGame(new ReachGardenSettings(), 3, 2, 1);
            Assert.Throws<ArgumentNullException>(() => game.ApplySettings(null));
            Assert.Throws<ArgumentException>(() => game.ApplySettings(new ReachGardenSettings { TargetRadius = 0 }));
            Assert.AreEqual(0.5, game.TargetRadius);
        }
    }
}
