using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Threading;

namespace MotionPlay.Networking
{
    /// <summary>Socket worker with no Unity calls; snapshots are the only data handoff.</summary>
    public sealed class UdpStateListener : IDisposable
    {
        private readonly ReceiverConfiguration configuration;
        private readonly object lifecycle = new object();
        private CvStateBuffer buffer;
        private Socket socket;
        private Thread worker;
        private volatile bool running;
        private string lastError;

        public bool IsRunning => running;
        public string LastError => Volatile.Read(ref lastError);
        public static double MonotonicSeconds => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency;

        public UdpStateListener(ReceiverConfiguration configuration)
        {
            this.configuration = configuration ?? throw new ArgumentNullException(nameof(configuration));
            buffer = new CvStateBuffer(configuration.TimeoutSeconds);
        }

        public void Start()
        {
            lock (lifecycle)
            {
                if (running) return;
                if (worker != null) throw new InvalidOperationException("Stop the previous listener before restarting.");
                var nextSocket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
                try
                {
                    nextSocket.ExclusiveAddressUse = true;
                    nextSocket.ReceiveTimeout = 100;
                    nextSocket.Bind(new IPEndPoint(IPAddress.Loopback, configuration.Port));
                    buffer = new CvStateBuffer(configuration.TimeoutSeconds);
                    Volatile.Write(ref lastError, null);
                    socket = nextSocket;
                    running = true;
                    CvStateBuffer nextBuffer = buffer;
                    worker = new Thread(() => ReceiveLoop(nextSocket, nextBuffer))
                    { IsBackground = true, Name = "MotionPlay UDP receive" };
                    worker.Start();
                }
                catch
                {
                    running = false;
                    worker = null;
                    socket = null;
                    nextSocket.Dispose();
                    throw;
                }
            }
        }

        public ReceiverSnapshot Read() => buffer.Read(MonotonicSeconds);

        private void ReceiveLoop(Socket ownedSocket, CvStateBuffer ownedBuffer)
        {
            var bytes = new byte[CvStateCodec.MaxDatagramBytes + 1];
            EndPoint source = new IPEndPoint(IPAddress.Any, 0);
            try
            {
                while (running)
                {
                    int count;
                    try { count = ownedSocket.ReceiveFrom(bytes, ref source); }
                    catch (SocketException error) when (error.SocketErrorCode == SocketError.TimedOut ||
                        error.SocketErrorCode == SocketError.WouldBlock) { continue; }
                    catch (SocketException error) when (error.SocketErrorCode == SocketError.MessageSize)
                    { ownedBuffer.RecordInvalid(); continue; }
                    if (!running) break;
                    if (!(source is IPEndPoint sender) || !IPAddress.IsLoopback(sender.Address) ||
                        !CvStateCodec.TryDecode(bytes, count, out CvState state))
                    { ownedBuffer.RecordInvalid(); continue; }
                    ownedBuffer.TryAccept(state, MonotonicSeconds);
                }
            }
            // A worker boundary must report failures to the owner, rather than
            // let an unhandled background exception terminate the Unity process.
            catch (Exception)
            {
                if (running) Volatile.Write(ref lastError, "UDP reception stopped; disable/re-enable the receiver and check the port/firewall.");
            }
            finally
            {
                running = false;
                ownedBuffer.ClearState();
                ownedSocket.Dispose();
            }
        }

        /// <summary>Close to unblock receive, then join with a finite wait; safe to repeat.</summary>
        public void Stop()
        {
            lock (lifecycle)
            {
                running = false;
                socket?.Dispose();
                socket = null;
                if (worker != null && !worker.Join(1000))
                {
                    Volatile.Write(ref lastError, "UDP worker did not stop within one second; restart Play Mode before rebinding.");
                    buffer.ClearState();
                    return;
                }
                worker = null;
                buffer.ClearState();
            }
        }

        public void Dispose() => Stop();
    }
}
