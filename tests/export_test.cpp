#include <gtest/gtest.h>

#include <sstream>
#include <string>
#include <vector>

#include "lobstudy/export.hpp"

namespace {

using itch::ReplayOp;

ReplayOp add(std::uint64_t id, ob::Side s, std::int64_t px, std::uint64_t qty, std::uint64_t ts) {
    return {ReplayOp::Kind::Add,
            ob::Order{ob::OrderId{id}, s, ob::OrderType::Limit, ob::Price{px}, ob::Quantity{qty}}, ts};
}
ReplayOp cancel(std::uint64_t id, ob::Side s, std::int64_t px, std::uint64_t ts) {
    return {ReplayOp::Kind::Cancel,
            ob::Order{ob::OrderId{id}, s, ob::OrderType::Limit, ob::Price{px}, ob::Quantity{0}}, ts};
}
ReplayOp reduce(std::uint64_t id, ob::Side s, std::int64_t px, std::uint64_t remaining, std::uint64_t ts) {
    return {ReplayOp::Kind::Reduce,
            ob::Order{ob::OrderId{id}, s, ob::OrderType::Limit, ob::Price{px}, ob::Quantity{remaining}}, ts};
}

std::vector<std::string> rows(const std::vector<ReplayOp>& ops, lobstudy::ExportStats* st = nullptr) {
    std::ostringstream out;
    const auto s = lobstudy::export_ops(ops, out);
    if (st) *st = s;
    std::vector<std::string> lines;
    std::istringstream in(out.str());
    for (std::string l; std::getline(in, l);) lines.push_back(l);
    return lines;
}

constexpr auto B = ob::Side::Buy;
constexpr auto S = ob::Side::Sell;

}  // namespace

TEST(Export, HeaderIsExact) {
    auto r = rows({});
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0], "seq,ts_ns,bid_px,bid_qty,ask_px,ask_qty");
}

TEST(Export, OneSidedBookWritesZerosForEmptySide) {
    lobstudy::ExportStats st;
    auto r = rows({add(1, B, 10000, 100, 5)}, &st);
    ASSERT_EQ(r.size(), 2u);
    EXPECT_EQ(r[1], "0,5,10000,100,0,0");
    EXPECT_EQ(st.one_sided, 1u);
    EXPECT_EQ(st.crossed, 0u);
}

// Hand-computed: two bids at 1.0000 (100 + 50), one at 0.9900, one ask at 1.0100.
TEST(Export, KnownAnswerTopOfBookSumsTheBestLevel) {
    auto r = rows({add(1, B, 10000, 100, 10), add(2, B, 10000, 50, 20), add(3, B, 9900, 70, 30),
                   add(4, S, 10100, 200, 40)});
    ASSERT_EQ(r.size(), 5u);
    EXPECT_EQ(r[1], "0,10,10000,100,0,0");
    EXPECT_EQ(r[2], "1,20,10000,150,0,0");
    EXPECT_EQ(r[3], "2,30,10000,150,0,0");
    EXPECT_EQ(r[4], "3,40,10000,150,10100,200");
}

TEST(Export, CancellingTheBestLevelMovesToTheNextOne) {
    auto r = rows({add(1, B, 10000, 100, 1), add(2, B, 9900, 70, 2), add(3, S, 10100, 200, 3),
                   cancel(1, B, 10000, 4)});
    ASSERT_EQ(r.size(), 5u);
    EXPECT_EQ(r[4], "3,4,9900,70,10100,200");
}

TEST(Export, ReduceShrinksTheLevelInPlace) {
    auto r = rows({add(1, B, 10000, 100, 1), add(2, B, 10000, 50, 2), add(3, S, 10100, 200, 3),
                   reduce(1, B, 10000, 40, 4), reduce(3, S, 10100, 5, 5)});
    ASSERT_EQ(r.size(), 6u);
    EXPECT_EQ(r[4], "3,4,10000,90,10100,200");
    EXPECT_EQ(r[5], "4,5,10000,90,10100,5");
}

TEST(Export, SeqCountsOpsAndTsIsCopiedFromEachOp) {
    auto r = rows({add(1, S, 10100, 10, 34'500'000'000'000ULL), add(2, B, 10000, 10, 34'500'000'000'001ULL)});
    ASSERT_EQ(r.size(), 3u);
    EXPECT_EQ(r[1], "0,34500000000000,0,0,10100,10");
    EXPECT_EQ(r[2], "1,34500000000001,10000,10,10100,10");
}

TEST(Export, SameInputGivesIdenticalOutput) {
    std::vector<ReplayOp> ops;
    for (std::uint64_t i = 1; i <= 2000; ++i) {
        const bool bid = i % 2 == 1;
        const std::int64_t px = bid ? 10000 - static_cast<std::int64_t>(i % 7) : 10100 + static_cast<std::int64_t>(i % 5);
        ops.push_back(add(i, bid ? B : S, px, i, i));
    }
    for (std::uint64_t i = 1; i <= 2000; i += 3) ops.push_back(cancel(i, i % 2 == 1 ? B : S, 0, 3000 + i));
    std::ostringstream a, b;
    lobstudy::export_ops(ops, a);
    lobstudy::export_ops(ops, b);
    EXPECT_EQ(a.str(), b.str());
}
