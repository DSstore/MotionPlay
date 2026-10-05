using System;
using MotionPlay.Games;
using NUnit.Framework;

namespace MotionPlay.Tests
{
    public sealed class ReachGardenStatsTests
    {
        private const double Frame = 1.0 / 30;

        private static ReachGardenGame Started(ReachGardenSettings settings = null)
        {
            var game = new ReachGardenGame(settings ?? new ReachGardenSettings(), 3.0, 2.0, 7);
            game.Step(Frame, true, 0, 0);
            return game;
        }

        /// <summary>Move the cursor in a straight line, ending exactly at the destination.</summary>
        private static void Glide(ReachGardenGame game, double fromX, double fromY, double toX, double toY, int steps)
        {
            for (int i = 1; i <= steps; i++)
            {
                double t = (double)i / steps;
                game.Step(Frame, true, fromX + (toX - fromX) * t, fromY + (toY - fromY) * t);
            }
        }

        /// <summary>Approach the active target from 2 units to its left and hold on it until it is watered.</summary>
        private static void Approach(ReachGardenGame game)
        {
            int attempted = game.Stats.Attempted;
            double tx = game.TargetX, ty = game.TargetY;
            game.Step(Frame, true, tx - 2, ty);
            Glide(game, tx - 2, ty, tx, ty, 20);
            for (int i = 0; i < 200 && game.Stats.Attempted == attempted; i++) game.Step(Frame, true, tx, ty);
            Assert.AreEqual(attempted + 1, game.Stats.Attempted);
        }

        private static void Miss(ReachGardenGame game)
        {
            int attempted = game.Stats.Attempted;
            double tx = game.TargetX, ty = game.TargetY;
            for (int i = 0; i < 1000 && game.Stats.Attempted == attempted; i++) game.Step(Frame, true, tx - 2, ty);
            Assert.AreEqual(attempted + 1, game.Stats.Attempted);
        }

        [Test]
        public void MetricsAreNullBeforeAnyFlowerFinishes()
        {
            ReachGardenStats stats = Started().Stats;
            Assert.IsNull(stats.Accuracy);
            Assert.IsNull(stats.AverageReactionTime);
            Assert.IsNull(stats.AverageMovementTime);
            Assert.IsNull(stats.AverageHoldStability);
            Assert.IsNull(stats.AveragePathEfficiency);
            Assert.AreEqual(0, stats.Score);
        }

        [Test]
        public void DirectApproachGivesFullAccuracyAndHighEfficiency()
        {
            ReachGardenGame game = Started();
            Approach(game);
            ReachGardenStats stats = game.Stats;
            Assert.AreEqual(1, stats.Watered);
            Assert.AreEqual(1.0, stats.Accuracy.Value, 1e-9);
            Assert.Greater(stats.AverageReactionTime.Value, 0);
            Assert.Less(stats.AverageReactionTime.Value, 0.2);
            Assert.Greater(stats.AverageMovementTime.Value, 0);
            Assert.AreEqual(1.0, stats.AverageHoldStability.Value, 1e-9);
            Assert.Greater(stats.AveragePathEfficiency.Value, 0.99);
        }

        [Test]
        public void DetourLowersPathEfficiency()
        {
            ReachGardenGame game = Started();
            double tx = game.TargetX, ty = game.TargetY;
            game.Step(Frame, true, tx - 2, ty);
            Glide(game, tx - 2, ty, tx - 2, ty + 2, 20);
            Glide(game, tx - 2, ty + 2, tx, ty, 20);
            for (int i = 0; i < 200 && game.Stats.Attempted == 0; i++) game.Step(Frame, true, tx, ty);
            Assert.Less(game.Stats.AveragePathEfficiency.Value, 0.8);
            Assert.Greater(game.Stats.AveragePathEfficiency.Value, 0.3);
        }

        [Test]
        public void LeavingTheFlowerLowersHoldStability()
        {
            ReachGardenGame game = Started();
            double tx = game.TargetX, ty = game.TargetY;
            game.Step(Frame, true, tx - 2, ty);
            Glide(game, tx - 2, ty, tx, ty, 20);
            for (int i = 0; i < 9; i++) game.Step(Frame, true, tx, ty);
            for (int i = 0; i < 3; i++) game.Step(Frame, true, tx + 2, ty);
            for (int i = 0; i < 200 && game.Stats.Attempted == 0; i++) game.Step(Frame, true, tx, ty);
            Assert.AreEqual(1, game.Stats.Watered);
            Assert.Less(game.Stats.AverageHoldStability.Value, 1.0);
            Assert.Greater(game.Stats.AverageHoldStability.Value, 0.6);
        }

        [Test]
        public void MissedFlowerNeverEnteredHasNoTimingSamples()
        {
            ReachGardenGame game = Started();
            Miss(game);
            ReachGardenStats stats = game.Stats;
            Assert.AreEqual(0, stats.Watered);
            Assert.AreEqual(0.0, stats.Accuracy.Value, 1e-9);
            Assert.IsNull(stats.AverageReactionTime);
            Assert.IsNull(stats.AverageHoldStability);
            Assert.IsNull(stats.AveragePathEfficiency);
        }

        [Test]
        public void StreakResetsOnMissAndBestStreakIsKept()
        {
            ReachGardenGame game = Started();
            Approach(game);
            Approach(game);
            Assert.AreEqual(2, game.Stats.CurrentStreak);
            Miss(game);
            Assert.AreEqual(0, game.Stats.CurrentStreak);
            Approach(game);
            Assert.AreEqual(1, game.Stats.CurrentStreak);
            Assert.AreEqual(2, game.Stats.BestStreak);
            Assert.AreEqual(3, game.Stats.Watered);
            Assert.AreEqual(4, game.Stats.Attempted);
            Assert.AreEqual(0.75, game.Stats.Accuracy.Value, 1e-9);
        }

        [Test]
        public void LostTrackingOnTheApproachSkipsPathEfficiencyOnly()
        {
            ReachGardenGame game = Started();
            double tx = game.TargetX, ty = game.TargetY;
            game.Step(Frame, true, tx - 2, ty);
            Glide(game, tx - 2, ty, tx - 1.5, ty, 5);
            for (int i = 0; i < 5; i++) game.Step(Frame, false, 0, 0);
            Glide(game, tx - 1.5, ty, tx, ty, 10);
            for (int i = 0; i < 200 && game.Stats.Attempted == 0; i++) game.Step(Frame, true, tx, ty);
            Assert.AreEqual(1, game.Stats.Watered);
            Assert.IsNotNull(game.Stats.AverageReactionTime);
            Assert.IsNull(game.Stats.AveragePathEfficiency);
        }

        [Test]
        public void StatsResetWhenARoundRestarts()
        {
            ReachGardenGame game = Started();
            Approach(game);
            Assert.Greater(game.Stats.DurationSeconds, 0);
            game.Restart();
            ReachGardenStats stats = game.Stats;
            Assert.AreEqual(0, stats.Attempted);
            Assert.AreEqual(0, stats.BestStreak);
            Assert.AreEqual(0, stats.DurationSeconds);
            Assert.IsNull(stats.Accuracy);
            Assert.IsNull(stats.AverageReactionTime);
        }

        [Test]
        public void FullRoundCountsEveryFlowerAndStaysInRange()
        {
            ReachGardenGame game = Started();
            while (game.Phase == ReachGardenPhase.Playing)
            {
                if (game.TargetIndex % 2 == 0) Approach(game); else Miss(game);
            }
            ReachGardenStats stats = game.Stats;
            Assert.AreEqual(game.TargetCount, stats.Attempted);
            Assert.AreEqual(game.TargetsWatered, stats.Watered);
            Assert.AreEqual(0.5, stats.Accuracy.Value, 1e-9);
            Assert.AreEqual(1, stats.BestStreak);
            foreach (double? ratio in new[] { stats.AverageHoldStability, stats.AveragePathEfficiency })
            {
                Assert.GreaterOrEqual(ratio.Value, 0);
                Assert.LessOrEqual(ratio.Value, 1);
            }
        }
    }
}
