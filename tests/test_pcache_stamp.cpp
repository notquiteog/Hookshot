// tests/test_pcache_stamp.py compiles and runs this: gpu/vk/pcache_stamp.h, what the pipeline cache's files were made for.
#include "../gpu/vk/pcache_stamp.h"

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <string>

static int failed;
#define CHECK(x)                                                \
    do {                                                        \
        if (!(x)) {                                             \
            std::printf("FAILED line %d: %s\n", __LINE__, #x);  \
            failed++;                                           \
        }                                                       \
    } while (0)

static void put(const std::string& path, size_t bytes) {
    FILE* f = fopen(path.c_str(), "wb");
    for (size_t i = 0; i < bytes; i++) fputc('x', f);
    fclose(f);
}
static bool there(const std::string& path) { return std::filesystem::exists(path); }

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string dir = std::string(argv[1]) + "/";
    using namespace pcache_stamp;

    // the names it takes for the cache's: the main file and the play files, with their .tmp; nothing else in the folder
    CHECK(is_cache_file("hookshot_pipeline_cache.bin") && is_cache_file("hookshot_pipeline_cache.bin.tmp"));
    CHECK(is_cache_file("hookshot_pipeline_cache_play_1.bin") && is_cache_file("hookshot_pipeline_cache_play_123.bin.tmp"));
    CHECK(!is_cache_file("hookshot_pipeline_cache.stamp") && !is_cache_file("hookshot_programs.bin") && !is_cache_file("hookshot_pipelines.bin"));
    CHECK(!is_cache_file("hookshot_pipeline_cache_play_.bin") && !is_cache_file("hookshot_pipeline_cache_play_x.bin") &&
          !is_cache_file("hookshot_pipeline_cache_play_1.txt") && !is_cache_file("hookshot_pipeline_cache_play_1"));
    CHECK(!is_cache_file("old_hookshot_pipeline_cache.bin") && !is_cache_file("save.bin"));

    // a folder from before the stamp file: its cache files go, the others stay, and the stamp is written
    put(dir + "hookshot_pipeline_cache.bin", 3000);
    put(dir + "hookshot_pipeline_cache_play_1.bin", 200);
    put(dir + "hookshot_pipeline_cache_play_7.bin", 100);
    put(dir + "hookshot_programs.bin", 50);
    put(dir + "save.bin", 10);
    Dropped d = check(dir, 0x1234);
    CHECK(d.files == 3 && d.bytes == 3300);
    CHECK(!there(dir + "hookshot_pipeline_cache.bin") && !there(dir + "hookshot_pipeline_cache_play_1.bin") && !there(dir + "hookshot_pipeline_cache_play_7.bin"));
    CHECK(there(dir + "hookshot_programs.bin") && there(dir + "save.bin"));
    uint64_t s = 0;
    CHECK(read(dir, &s) && s == 0x1234);

    // the same stamp: nothing goes
    put(dir + "hookshot_pipeline_cache.bin", 4000);
    put(dir + "hookshot_pipeline_cache_play_2.bin", 300);
    d = check(dir, 0x1234);
    CHECK(d.files == 0 && there(dir + "hookshot_pipeline_cache.bin") && there(dir + "hookshot_pipeline_cache_play_2.bin"));

    // another translator: they go, the stamp is the new one
    d = check(dir, 0x5678);
    CHECK(d.files == 2 && d.bytes == 4300 && !there(dir + "hookshot_pipeline_cache.bin"));
    CHECK(read(dir, &s) && s == 0x5678);

    // an empty folder: nothing to drop, the stamp written; a damaged stamp file counts as none
    d = check(dir, 0x5678);
    CHECK(d.files == 0);
    put(dir + "hookshot_pipeline_cache.stamp", 3);
    CHECK(!read(dir, &s));
    put(dir + "hookshot_pipeline_cache.bin", 10);
    d = check(dir, 0x5678);
    CHECK(d.files == 1 && read(dir, &s) && s == 0x5678);
    put(dir + "hookshot_pipeline_cache.stamp", 9);   // (a byte too many)
    CHECK(!read(dir, &s));

    // the old names (mkw_vk_pipelines*, before scripts/rename_nx2.py): taken for the cache's too, and moved to the new names
    CHECK(is_cache_file("mkw_vk_pipelines.bin") && is_cache_file("mkw_vk_pipelines_play_4.bin") && !is_cache_file("mkw_vk_pipelines.stamp"));
    const std::string m = dir + "migrate/";
    std::filesystem::create_directory(m);
    put(m + "mkw_vk_pipelines.bin", 5000);
    put(m + "mkw_vk_pipelines.stamp", 8);
    put(m + "mkw_vk_pipelines_play_3.bin", 70);
    put(m + "mkw_vk_pipelines_play_12.bin", 80);
    put(m + "mkw_vk_pipelines_play_x.bin", 5);   // (not a play file: stays)
    put(m + "hookshot_programs.bin", 50);
    CHECK(migrate(m) == 4);
    CHECK(there(m + "hookshot_pipeline_cache.bin") && std::filesystem::file_size(m + "hookshot_pipeline_cache.bin") == 5000);
    CHECK(there(m + "hookshot_pipeline_cache.stamp") && there(m + "hookshot_pipeline_cache_play_3.bin") &&
          there(m + "hookshot_pipeline_cache_play_12.bin"));
    CHECK(!there(m + "mkw_vk_pipelines.bin") && !there(m + "mkw_vk_pipelines.stamp") && !there(m + "mkw_vk_pipelines_play_3.bin") &&
          !there(m + "mkw_vk_pipelines_play_12.bin"));
    CHECK(there(m + "mkw_vk_pipelines_play_x.bin") && there(m + "hookshot_programs.bin"));
    CHECK(migrate(m) == 0);   // (again: nothing left to move)
    // (the moved stamp still vouches for the moved cache: nothing is dropped for the rename)
    uint64_t kept = 0;
    CHECK(read(m, &kept));
    d = check(m, kept);
    CHECK(d.files == 0 && there(m + "hookshot_pipeline_cache.bin"));
    // both names (an older build ran here again): the newer is kept under the new name, the other goes, never both
    const auto aged = [](const std::string& path, int seconds) {
        std::filesystem::last_write_time(path, std::filesystem::file_time_type::clock::now() - std::chrono::seconds(seconds));
    };
    put(m + "mkw_vk_pipelines.bin", 6000);   // (newer than the new name's)
    aged(m + "hookshot_pipeline_cache.bin", 3600);
    CHECK(migrate(m) == 1 && std::filesystem::file_size(m + "hookshot_pipeline_cache.bin") == 6000 && !there(m + "mkw_vk_pipelines.bin"));
    put(m + "mkw_vk_pipelines.bin", 7000);   // (older than the new name's)
    aged(m + "mkw_vk_pipelines.bin", 7200);
    CHECK(migrate(m) == 1 && std::filesystem::file_size(m + "hookshot_pipeline_cache.bin") == 6000 && !there(m + "mkw_vk_pipelines.bin"));
    CHECK(migrate(dir + "not-there/") == 0);

    if (failed) return 1;
    std::printf("pcache_stamp: ok\n");
    return 0;
}
