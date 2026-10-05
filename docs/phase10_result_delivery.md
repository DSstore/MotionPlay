# Phase 10: Result delivery and storage

## What changed

When a Reach Garden round completes, Unity sends one `SESSION_END` result to a
Python receiver. The receiver validates it, stores it once, and replies with an
acknowledgement. Unity retries until it hears back and tells you whether the result
was actually saved.

```text
ReachGardenController ──► ResultSender ──UDP 5006──► backend.result_receiver ──► ResultStore
        ▲                      │  ▲                          │                    ├─ JSONL file (default)
        │                      │  └──── RESULT_ACK ──────────┘                    └─ MongoDB (--store mongo)
   round complete         ResultDelivery (retry / confirm bookkeeping)
```

- `Core/SessionResult.cs` builds the message from round statistics and decodes acknowledgements.
- `Core/ResultDelivery.cs` is the retry state machine (no sockets, so it is unit tested).
- `Runtime/ResultSender.cs` owns the loopback socket and is added to the Reach Garden object automatically.
- `shared/protocol.py` validates `SESSION_END` and encodes `RESULT_ACK`.
- `backend/result_receiver.py` is the receiver; `backend/storage.py` holds the two stores.

Message fields and acknowledgement statuses are in the [UDP protocol](udp_protocol.md).

## Delivery rules

- **Idempotent:** every round has a `session_id`. Resending a stored round gets `duplicate`, never a second copy.
- **Retries:** Unity sends up to 5 times, 1 second apart (`maxAttempts` and `retrySeconds` on the **Result Sender** component).
- **Honest status:** the HUD shows "Saving result", "Result saved", "Result rejected", or "Result NOT saved (receiver off?)". UDP acceptance by the OS is never treated as delivery.
- **Storage failure:** if the receiver cannot write, it answers `error` and Unity keeps retrying.
- **Not kept for later:** a round that ends while the receiver is off is reported as not saved and is not queued across Play sessions. Pressing **R** mid-round abandons that round and sends nothing.
- **Loopback only:** the receiver binds `127.0.0.1`.

## Storage

| Store | How | Notes |
|---|---|---|
| JSONL (default) | `data/results.jsonl`, one JSON object per line | No database needed; `data/` is ignored by Git; dedupes by `session_id`, including after a restart |
| MongoDB | `--store mongo` uses `MONGODB_URI` and `MONGODB_DATABASE` from `.env` | Collection `sessions` with a unique index on `session_id` |

MongoDB is not installed on the development machine, so the MongoDB store is covered
by unit tests with a fake client only and has not been run against a real server.

## Run it on Windows 11

1. Start the receiver:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.result_receiver
   ```

   Options: `--store mongo`, `--file path.jsonl`, `--port`, `--max-results`, `--timeout`.
2. In Unity, play **ReachGarden** and start the CV engine as in the [Phase 8 guide](phase8_reach_garden.md).
3. Finish a round. The HUD ends with "Result saved" and the receiver logs `Result … stored`.
4. Open `data/results.jsonl` and check the line matches the on-screen statistics.

## Acceptance checklist

- [ ] With the receiver running, finishing a round shows "Result saved" and adds one line to `data/results.jsonl`.
- [ ] Unity's Console logs an acknowledgement; the receiver logs `stored`.
- [ ] With the receiver stopped, the HUD shows "Saving result" and then "Result NOT saved" after about 5 seconds, with a warning in the Console.
- [ ] Start the receiver within a few seconds of the round ending and the result is still saved, once.
- [ ] Playing again adds a second line with a different `session_id`; the file never holds the same `session_id` twice.
- [ ] Pressing **R** mid-round does not add a line.
- [ ] Stop and restart the receiver; earlier results remain and are not duplicated.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
```

Python adds 11 cases (validation, null metrics, malformed packets, JSONL and MongoDB
stores, every acknowledgement path, and real loopback delivery). The C# harness has
106 cases, 10 of them new (encoding, acknowledgement decoding, retry schedule,
not-confirmed, error and final acknowledgements, ordering, argument checks, and the
result port setting). The Unity sender, the HUD line, and the end-to-end flow need
the manual checklist above in the Unity Editor.

This is a gameplay prototype for a portfolio project, not a medical device or therapy tool.
