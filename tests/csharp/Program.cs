using System;
using System.Diagnostics;
using System.Threading;
using MotionPlay.Networking;
using Newtonsoft.Json.Linq;
using NUnitLite;

/// <summary>Runs the same core tests outside Unity; probe mode supports Python interoperability checks.</summary>
internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length != 2 || args[0] != "--probe") return new AutoRun().Execute(args);
        using (var listener = new UdpStateListener(new ReceiverConfiguration(int.Parse(args[1]))))
        {
            listener.Start();
            Console.WriteLine("READY");
            long lastAccepted = 0;
            var clock = Stopwatch.StartNew();
            while (clock.Elapsed.TotalSeconds < 10)
            {
                var snapshot = listener.Read();
                if (snapshot.Accepted > lastAccepted && snapshot.State != null)
                {
                    lastAccepted = snapshot.Accepted;
                    var state = snapshot.State;
                    Console.WriteLine(new JObject
                    {
                        ["tracking"] = state.Tracking, ["sequence"] = state.Sequence,
                        ["gesture"] = state.Gesture, ["stream_id"] = state.StreamId,
                        ["accepted"] = snapshot.Accepted, ["invalid"] = snapshot.Invalid,
                        ["position"] = state.Position == null ? (JToken)JValue.CreateNull() :
                            new JObject { ["x"] = state.Position.X, ["y"] = state.Position.Y, ["z"] = state.Position.Z }
                    }.ToString(Newtonsoft.Json.Formatting.None));
                }
                if (lastAccepted > 0 && snapshot.State == null)
                {
                    Console.WriteLine("TIMEOUT");
                    return 0;
                }
                if (!listener.IsRunning) return 2;
                Thread.Sleep(2);
            }
            return 1;
        }
    }
}
