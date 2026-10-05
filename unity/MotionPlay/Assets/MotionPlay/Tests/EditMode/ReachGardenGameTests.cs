using System;
using MotionPlay.Games;
using NUnit.Framework;

namespace MotionPlay.Tests
{
    public sealed class ReachGardenGameTests
    {
        private const double Frame = 1.0 / 30;

        private static ReachGardenGame NewGame(ReachGardenSettings settings = null, int seed = 7)
            => new ReachGardenGame(settings ?? new ReachGardenSettings(), 3.0, 2.0, seed);

        private static ReachGardenGame Started(ReachGardenSettings settings = null, int seed = 7)
        {
            ReachGardenGame game = NewGame(settings, seed);
            game.Step(Frame, true, 0, 0);
            return game;
        }

        /// <summary>Hold the cursor on the active target until it is watered (or give up after a bound).</summary>
        private static void Water(ReachGardenGame game)
        {
            int watered = game.TargetsWatered;
            for (int i = 0; i < 200 && game.TargetsWatered == watered; i++)
                game.Step(Frame, true, game.TargetX, game.TargetY);
            Assert.AreEqual(watered + 1, game.TargetsWatered);
        }

        [Test]
        public void WaitsUntilTheHandIsTracked()
        {
            ReachGardenGame game = NewGame();
            game.Step(Frame, false, 0, 0);
            Assert.AreEqual(ReachGardenPhase.WaitingForHand, game.Phase);
            game.Step(Frame, true, 0, 0);
            Assert.AreEqual(ReachGardenPhase.Playing, game.Phase);
            Assert.AreEqual(0, game.TargetIndex);
        }

        [Test]
        public void TargetsAreWithinBoundsAndSeparated()
        {
            ReachGardenGame game = Started();
            for (int i = 0; i < 7; i++)
            {
                double px = game.TargetX, py = game.TargetY;
                Water(game);
                Assert.LessOrEqual(Math.Abs(game.TargetX), 3.0);
                Assert.LessOrEqual(Math.Abs(game.TargetY), 2.0);
                if (game.Phase == ReachGardenPhase.Playing)
                    Assert.GreaterOrEqual(Math.Sqrt(Math.Pow(game.TargetX - px, 2) + Math.Pow(game.TargetY - py, 2)), 1.5 - 1e-9);
            }
        }

        [Test]
        public void SameSeedGivesSameLayout()
        {
            ReachGardenGame a = Started(null, 42), b = Started(null, 42);
            Assert.AreEqual(a.TargetX, b.TargetX);
            Assert.AreEqual(a.TargetY, b.TargetY);
        }

        [Test]
        public void HoldingOnTargetWatersItAndAdvances()
        {
            ReachGardenGame game = Started();
            Water(game);
            Assert.AreEqual(1, game.TargetsWatered);
            Assert.AreEqual(1, game.TargetIndex);
            Assert.AreEqual(0, game.DwellProgress, 1e-12);
        }

        [Test]
        public void ProgressBuildsWhileInsideAndDrainsWhenOutside()
        {
            ReachGardenGame game = Started();
            for (int i = 0; i < 12; i++) game.Step(Frame, true, game.TargetX, game.TargetY);
            double built = game.DwellProgress;
            Assert.Greater(built, 0.3);
            Assert.Less(built, 1);
            game.Step(Frame, true, game.TargetX + 10, game.TargetY);
            Assert.Less(game.DwellProgress, built);
        }

        [Test]
        public void CursorOutsideTargetRadiusNeverWaters()
        {
            ReachGardenGame game = Started();
            for (int i = 0; i < 60; i++) game.Step(Frame, true, game.TargetX + 0.6, game.TargetY);
            Assert.AreEqual(0, game.TargetsWatered);
        }

        [Test]
        public void TargetTimesOutOnlyWhileTracked()
        {
            var settings = new ReachGardenSettings { TargetTimeoutSeconds = 2 };
            ReachGardenGame game = Started(settings);
            for (int i = 0; i < 300; i++) game.Step(Frame, false, 0, 0);
            Assert.AreEqual(0, game.TargetsMissed);
            Assert.AreEqual(2, game.TimeRemaining, 1e-9);
            for (int i = 0; i < 90; i++) game.Step(Frame, true, game.TargetX + 10, game.TargetY);
            Assert.AreEqual(1, game.TargetsMissed);
            Assert.AreEqual(1, game.TargetIndex);
        }

        [Test]
        public void LosingTheHandMidDwellDrainsProgress()
        {
            ReachGardenGame game = Started();
            for (int i = 0; i < 12; i++) game.Step(Frame, true, game.TargetX, game.TargetY);
            double built = game.DwellProgress;
            game.Step(Frame, false, game.TargetX, game.TargetY);
            Assert.Less(game.DwellProgress, built);
        }

        [Test]
        public void LargeFrameStepCannotCompleteATarget()
        {
            ReachGardenGame game = Started();
            game.Step(5, true, game.TargetX, game.TargetY);
            Assert.AreEqual(0, game.TargetsWatered);
        }

        [Test]
        public void RoundCompletesAfterTargetCountWithMixedOutcomes()
        {
            var settings = new ReachGardenSettings { TargetCount = 3, TargetTimeoutSeconds = 1 };
            ReachGardenGame game = Started(settings);
            Water(game);
            for (int i = 0; i < 60 && game.TargetsMissed == 0; i++) game.Step(Frame, true, game.TargetX + 10, game.TargetY);
            Assert.AreEqual(1, game.TargetsMissed);
            Water(game);
            Assert.AreEqual(ReachGardenPhase.Complete, game.Phase);
            Assert.AreEqual(2, game.TargetsWatered);
            Assert.AreEqual(1, game.TargetsMissed);
            Assert.AreEqual(3, game.TargetIndex);
        }

        [Test]
        public void CompletedRoundRestartsOnlyAfterLeavingThenDwellingOnRestartTarget()
        {
            var settings = new ReachGardenSettings { TargetCount = 1 };
            ReachGardenGame game = Started(settings);
            Water(game);
            Assert.AreEqual(ReachGardenPhase.Complete, game.Phase);
            // Cursor still near the previous spot; restart target is at the origin. Sitting on it must not restart.
            for (int i = 0; i < 60; i++) game.Step(Frame, true, 0, 0);
            Assert.AreEqual(ReachGardenPhase.Complete, game.Phase);
            game.Step(Frame, true, 2.5, 1.5);
            for (int i = 0; i < 60 && game.Phase == ReachGardenPhase.Complete; i++) game.Step(Frame, true, 0, 0);
            Assert.AreEqual(ReachGardenPhase.Playing, game.Phase);
            Assert.AreEqual(0, game.TargetsWatered);
            Assert.AreEqual(0, game.TargetIndex);
        }

        [Test]
        public void ManualRestartResetsCounters()
        {
            ReachGardenGame game = Started();
            Water(game);
            game.Restart();
            Assert.AreEqual(0, game.TargetsWatered);
            Assert.AreEqual(0, game.TargetIndex);
            Assert.AreEqual(ReachGardenPhase.Playing, game.Phase);
        }

        [Test]
        public void ShrinkingBoundsPullsTheActiveTargetInside()
        {
            ReachGardenGame game = Started();
            game.SetBounds(0.2, 0.2);
            Assert.LessOrEqual(Math.Abs(game.TargetX), 0.2);
            Assert.LessOrEqual(Math.Abs(game.TargetY), 0.2);
        }

        [Test]
        public void NonFiniteInputsAreIgnoredSafely()
        {
            ReachGardenGame game = Started();
            game.Step(double.NaN, true, 0, 0);
            game.Step(-1, true, 0, 0);
            game.Step(Frame, true, double.NaN, 0);
            Assert.AreEqual(0, game.TargetsWatered);
            Assert.AreEqual(ReachGardenPhase.Playing, game.Phase);
        }

        [Test]
        public void InvalidSettingsAndBoundsAreRejected()
        {
            Assert.Throws<ArgumentException>(() => NewGame(new ReachGardenSettings { TargetCount = 0 }));
            Assert.Throws<ArgumentException>(() => NewGame(new ReachGardenSettings { TargetRadius = 0 }));
            Assert.Throws<ArgumentException>(() => NewGame(new ReachGardenSettings { DwellSeconds = 9, TargetTimeoutSeconds = 8 }));
            Assert.Throws<ArgumentException>(() => new ReachGardenGame(new ReachGardenSettings(), 0, 2, 1));
            Assert.Throws<ArgumentException>(() => new ReachGardenGame(new ReachGardenSettings(), 3, double.NaN, 1));
            Assert.Throws<ArgumentNullException>(() => new ReachGardenGame(null, 3, 2, 1));
        }
    }
}
