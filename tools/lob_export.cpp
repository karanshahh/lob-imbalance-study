// lob_export <itch file> <out dir> <SYMBOL> [SYMBOL ...]
//
// One pass over an uncompressed Nasdaq ITCH 5.0 file. For each symbol, rebuilds the
// book with the orderbook v1 engine and writes <out dir>/<SYMBOL>.csv (see
// include/lobstudy/export.hpp for the columns). Prints one summary line per symbol.
// Exit codes: 0 ok, 1 usage or I/O error, 2 symbol not found, 3 book was crossed.

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "itch/itch.hpp"
#include "itch/replay.hpp"
#include "lobstudy/export.hpp"

namespace {
double secs_since(std::chrono::steady_clock::time_point t0) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "usage: %s <itch file> <out dir> <SYMBOL> [SYMBOL ...]\n", argv[0]);
        return 1;
    }
    const std::string path = argv[1];
    const std::filesystem::path out_dir = argv[2];
    std::vector<itch::ReplayBuilder> builders;
    for (int i = 3; i < argc; ++i) builders.emplace_back(argv[i]);

    itch::FileReader in(path);
    if (!in.ok()) { std::fprintf(stderr, "cannot open %s\n", path.c_str()); return 1; }
    std::error_code ec;
    std::filesystem::create_directories(out_dir, ec);
    if (ec) { std::fprintf(stderr, "cannot create %s\n", out_dir.c_str()); return 1; }

    const auto t_parse = std::chrono::steady_clock::now();
    std::span<const std::byte> msg;
    while (in.next(msg)) {
        const auto r = itch::decode(msg);
        for (auto& b : builders) {
            b.count(r);
            if (r) b.feed(*r);
        }
    }
    const double parse_s = secs_since(t_parse);
    std::printf("file %s\nparse_s %.2f messages %llu\n", path.c_str(), parse_s,
                static_cast<unsigned long long>(builders.front().stats().messages));

    int rc = 0;
    for (std::size_t i = 0; i < builders.size(); ++i) {
        const auto& b = builders[i];
        const std::string sym = argv[3 + i];
        if (!b.found_symbol()) { std::fprintf(stderr, "symbol %s not in file\n", sym.c_str()); rc = 2; continue; }
        const auto file = out_dir / (sym + ".csv");
        std::ofstream out(file, std::ios::binary | std::ios::trunc);
        if (!out) { std::fprintf(stderr, "cannot write %s\n", file.c_str()); return 1; }
        const auto t_export = std::chrono::steady_clock::now();
        const auto st = lobstudy::export_ops(b.ops(), out, b.peak_live());
        out.flush();
        if (!out) { std::fprintf(stderr, "write failed: %s\n", file.c_str()); return 1; }
        const double export_s = secs_since(t_export);
        std::printf("symbol %s ops %llu rows %llu crossed %llu one_sided %llu unknown_refs %llu peak_live %zu export_s %.3f\n",
                    sym.c_str(), static_cast<unsigned long long>(b.ops().size()),
                    static_cast<unsigned long long>(st.rows), static_cast<unsigned long long>(st.crossed),
                    static_cast<unsigned long long>(st.one_sided),
                    static_cast<unsigned long long>(b.stats().unknown_refs), b.peak_live(), export_s);
        if (st.crossed != 0 && rc == 0) rc = 3;
    }
    return rc;
}
