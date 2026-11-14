// (LaküenRecomp) Clues for the visual problems (the white haze, overbright rooms) in the log, for the master log
// (builder/linux/lakuen_report.py): every storage buffer a program could not bind (it reads zeros), counted by program for
// the whole run instead of the first 40 lines, every write-back wait that timed out (the CPU then reads what memory held),
// and the player's marks (the menu's "Mark a visual problem"): each mark logs what happened in the seconds before it.
// Lines start "lakuen-diag:" and "lakuen-mark:". LAKUEN_DIAG=0: none kept.
#pragma once

#include <cstdint>
#include <string>

namespace mkwvk {

bool diag_on();
/// A storage buffer of program key that could not be bound (stage, the address and size it asked for, written by it)
void diag_unbound(uint64_t key, int stage, uint64_t addr, uint64_t size, bool written);
/// A wait for a write-back that timed out: readback true for invalidate's, false for a capture's
void diag_wb_timeout(bool readback);
/// A draw of program key left out by the menu (an Effect row or the Effect finder)
void diag_left_out(uint64_t key);
/// Each present (the menu's tick): the summary every 30 s when something changed
void diag_tick();
/// The player's mark n: what the last seconds held
void diag_mark(int n);
/// A line kept for the report (the Effect finder's changes, with their time)
void diag_note(const char* line);
/// The menu's Create master log: masterlog-debugging.txt at path, everything above with the settings given (the menu's rows
/// as text); true when written
bool diag_write_report(const std::string& path, const std::string& settings);

} // namespace mkwvk
