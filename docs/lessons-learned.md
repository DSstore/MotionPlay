# Challenges and lessons learned

This is a short retrospective of the problems that were hardest to get right, written from the project's own history and logs. They are ordered roughly by how much they changed how the project is built.

## 1. The cursor that kept vanishing

**Symptom.** In live play the CV log showed the hand "lost" dozens of times in a few minutes, even when the player never left the camera's view.

**First guess, and it was wrong.** MediaPipe labels each frame's hand as left or right independently, so the first theory was that the label flips at random. A 20-second recording with the hand held still disproved it:
353 frames, all labelled right, zero flips, confidence about 0.96.

**What the data showed.** Repeating the recording with the hand moving the way it moves in play produced flips and low-confidence frames (19 `left` frames and 17 below the confidence gate in 341, with the full model). The problem
appears with motion, and it was worse at low frame rates, because at 10 FPS the hand moves further between frames. Two causes were stacked: the loop was slow (the full model took about 50 ms per frame), and a mislabelled frame counted as "no right hand".

**Fixes.** A lighter model roughly doubled the headless frame rate (17 to 29 FPS). A small stage, `cv_engine/continuity.py`, keeps a detection's label if it sits where that hand was a moment ago. It was deliberately written so that it
can never invent identity: a hand with no recent history, or one that appears elsewhere, is left exactly as MediaPipe reported it.

**Lessons.** Measure before fixing, and check the first hypothesis against data cheaply (here, a 20-second recording). Fix the cause you can show, and design the fix so its failure mode is "does nothing", not "does the wrong thing".

**A mistake along the way.** An early baseline of "142 lost events" was the count for the whole log file, which spanned several sessions, not for one run. Comparing a per-run number with it would have exaggerated the improvement. The corrected per-run
baseline (20 events) was used instead and the error was reported as soon as it was noticed. The lesson is to state the scope of a measurement every time.

## 2. A 29-second camera start

**Symptom.** The terminal sometimes seemed frozen, and Ctrl+C did nothing.

**Investigation.** The first attempt to reproduce it blamed the engine, and that attempt was wrong: a test harness reported the engine ignoring Ctrl+C, but a bare Python interpreter ignored it too. The harness's own environment passed an
"ignore Ctrl+C" flag to its child processes. Once Ctrl+C was properly enabled, the engine shut down cleanly in about a second, five times out of five, through PowerShell too. The real finding came from the logging added in Phase 17: it
printed `Opening the webcam took 29.0 s`. Nothing can interrupt the camera while Windows opens it, so Ctrl+C looked dead.

**Fix.** Timing the OpenCV backends showed Media Foundation (the default) taking about 6 s standalone and up to 29 s inside the engine, against about 1.2 s for DirectShow. Making DirectShow the default on Windows, with a fallback,
and skipping camera settings it already had, brought opening to about 2.6 s. A Q/Esc key to stop the headless engine was added as a second way out.

**Lessons.** A reproduction that also "reproduces" in a trivial control case is testing the harness, not the program, so always include a control. Instrument first: the logging phase paid for itself within one session. Fix the real
cause (a slow open), and still add the cheap fallback (a key to stop) for the symptom.

## 3. Tests that passed for the wrong reason

Several tests looked fine until they were run somewhere else:

- The start-script tests relied on the developer's own `.venv` and `.env`, so they failed on a fresh clone. Running the suite from a clean checkout of the pushed commit found it; the tests now use a fake project folder.
- A double-click launcher contained a literal tab character where a `\t` inside a path had been mangled during generation. A test that checks the launcher's exact bytes found it.
- A test that faked `perf_counter` with a fixed list of values broke the moment a legitimate extra call was added to the code under test.

To check that tests can actually fail, new tests were validated with **fault injection**: break the code on purpose (invert a flag, drop a log line, remove a guard) and confirm a test goes red. Every break was caught, and every edit reverted.
**Lesson:** a green test proves little until you have seen it fail for the right reason, and a clean clone is the cheapest second opinion.

## 4. Reliable results over an unreliable link

Hand state can be lossy, but a finished round must not be lost or duplicated. The solution is the classic one, kept small: every result carries a UUID; the receiver stores it once and answers with an acknowledgement; Unity retries until it hears one;
and a repeat is recognised by its UUID and answered `duplicate`. The receiver was also hardened to survive unexpected storage errors (it answers `error`, so Unity retries) and to rate-limit warnings about malformed packets so a noisy sender cannot fill the log.
**Lesson:** decide per message whether "latest wins" (hand state) or "must arrive exactly once" (results) is the right guarantee; they need different designs even on the same transport.

## 5. Documentation that drifts

By Phase 19 the README still said port 5006 was "reserved for future use" and quoted a test count that was out of date. The fix was a rewrite, but also tests: `tests/test_docs.py` fails when a link breaks, when the configuration reference
disagrees with the real defaults, or when a phase guide is missing from the README. **Lesson:** anything that can be checked mechanically should be, because docs go stale quietly.

## 6. Smaller lessons

- **Privacy shows up in logs.** The account log records failed logins but never a mistyped username that does not exist, because someone may have typed a password into the wrong box.
- **Honest scope beats an impressive claim.** There is no packaged installer because Unity and hundreds of megabytes of dependencies are still required; the scripts do what they say and the docs say what they do not do.
- **Qt's offscreen platform has no fonts.** Screenshots of the dashboard need the real platform, or the text is missing.
- **Keep decisions testable.** Putting game rules, statistics, difficulty and retry bookkeeping in engine-free code let 118 C# tests run without Unity, in seconds.
