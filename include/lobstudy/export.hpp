#pragma once
// Replays one symbol's book operations (built from ITCH by orderbook's ReplayBuilder)
// through the v1 order book, and writes the top of the book after every operation,
// one CSV row per op.
//
// Columns: seq, ts_ns, bid_px, bid_qty, ask_px, ask_qty
//   seq     index of the op: 0, 1, 2, ...
//   ts_ns   ITCH timestamp of the message that produced the op (ns since midnight ET)
//   *_px    best price in ITCH units (1/10,000 dollar); 0 when that side is empty
//   *_qty   shares resting at that best price; 0 when that side is empty
//
// No signal is computed here. Mid, imbalance and forward changes are computed in
// Python from these rows, so this side has one job and is easy to check.

#include <charconv>
#include <cstddef>
#include <cstdint>
#include <ostream>
#include <system_error>
#include <vector>

#include "itch/replay.hpp"
#include "orderbook/book.hpp"

namespace lobstudy {

struct Top {
    std::int64_t  bid_px = 0;
    std::uint64_t bid_qty = 0;
    std::int64_t  ask_px = 0;
    std::uint64_t ask_qty = 0;
    bool operator==(const Top&) const = default;
};

inline Top top_of_book(const ob::Book& b) {
    Top t;
    if (auto p = b.best_bid()) {
        t.bid_px = p->ticks;
        t.bid_qty = b.volume_at(ob::Side::Buy, *p).value;
    }
    if (auto p = b.best_ask()) {
        t.ask_px = p->ticks;
        t.ask_qty = b.volume_at(ob::Side::Sell, *p).value;
    }
    return t;
}

// The same three calls orderbook's tools/itch_replay.cpp makes for its v1 engine.
inline void apply(ob::Book& b, const itch::ReplayOp& op) {
    switch (op.kind) {
        case itch::ReplayOp::Kind::Add:    b.add(op.order); break;
        case itch::ReplayOp::Kind::Cancel: b.cancel(op.order.id); break;
        case itch::ReplayOp::Kind::Reduce: b.modify(op.order.id, op.order.price, op.order.remaining); break;
    }
}

struct ExportStats {
    std::uint64_t rows = 0;
    std::uint64_t crossed = 0;     // ops after which best bid >= best ask (a rebuilt book must keep this 0)
    std::uint64_t one_sided = 0;   // ops after which at least one side is empty
};

inline constexpr const char* kHeader = "seq,ts_ns,bid_px,bid_qty,ask_px,ask_qty\n";

// Writes the header and one row per op. `reserve_orders` pre-sizes the book's id index.
inline ExportStats export_ops(const std::vector<itch::ReplayOp>& ops, std::ostream& out,
                              std::size_t reserve_orders = 0) {
    ob::Book book;
    if (reserve_orders > 0) book.reserve(reserve_orders);
    out << kHeader;
    ExportStats st;
    char line[160];
    for (std::size_t i = 0; i < ops.size(); ++i) {
        apply(book, ops[i]);
        const Top t = top_of_book(book);
        if (book.crossed()) ++st.crossed;
        if (t.bid_qty == 0 || t.ask_qty == 0) ++st.one_sided;

        char* p = line;
        char* const end = line + sizeof(line);
        // Each number leaves one byte for its separator. Six numbers of at most 20 digits
        // plus separators need 126 bytes, so to_chars cannot fail here; if it ever did,
        // the field is written empty rather than past the buffer.
        auto put = [&](auto v, char sep) {
            const auto r = std::to_chars(p, end - 1, v);
            if (r.ec == std::errc{}) p = r.ptr;
            *p++ = sep;
        };
        put(static_cast<std::uint64_t>(i), ',');
        put(ops[i].ts, ',');
        put(t.bid_px, ',');
        put(t.bid_qty, ',');
        put(t.ask_px, ',');
        put(t.ask_qty, '\n');
        out.write(line, p - line);
        ++st.rows;
    }
    return st;
}

}  // namespace lobstudy
