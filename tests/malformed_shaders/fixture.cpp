// Malformed shader input is refused, not undefined behaviour. Authored instruction bits and IR only: no dump, game, GPU or driver.
// A broken or malicious mod, or a game bug, can hand the recompiler fields the hardware never encodes. Each case below must end in
// Shader::NotImplementedException (the translation's callers catch it, leave the program out and log it), and the well-formed
// neighbour of each must still translate:
//   - LDC's 5-bit constant buffer index past the 18 buffers (18, 31): at LDC, and as an immediate the info pass meets (constant
//     folding makes LDC's IS-mode index one) where it wrote constant_buffer_used_sizes[index] past its end and shifted 1U << index;
//   - ISBERD's 2-bit shift at 3 and 4-bit size at 4..15, which reached UNREACHABLE (__builtin_unreachable: undefined);
//   - a transform feedback varying wider than what is left of its location (5 components at element 0), which wrote past
//     output_generics[index]'s 4 elements and asked for F32[5].
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <string>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/exception.h"
#include "shader_recompiler/frontend/maxwell/translate/impl/impl.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/runtime_info.h"

using namespace Shader;

struct FixtureEnvironment final : Shader::Environment {
    explicit FixtureEnvironment(Stage s) { stage = s; }
    u64 ReadInstruction(u32) override { std::abort(); }
    u32 ReadCbufValue(u32, u32) override { return 0; }
    TextureType ReadTextureType(u32) override { return TextureType::Color2D; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return TexturePixelFormat::R8_UNORM; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {1, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return std::nullopt; }
    void Dump(u64, u64) override { std::abort(); }
};

static int failures, passes;

/// f must end in NotImplementedException (rejected) or not throw at all (accepted)
template <class F> static void expect(bool rejected, const char* what, F&& f) {
    std::string why;
    bool threw = false;
    try {
        f();
    } catch (const NotImplementedException& e) {
        threw = true, why = e.what();
    } catch (const std::exception& e) {
        std::printf("FAIL: %s: %s (not a NotImplementedException)\n", what, e.what());
        failures++;
        return;
    }
    if (threw != rejected) {
        std::printf("FAIL: %s: %s\n", what, rejected ? "accepted" : ("refused: " + why).c_str());
        failures++;
        return;
    }
    std::printf("ok: %s%s%s\n", what, rejected ? ": " : "", why.c_str());
    passes++;
}

/// One block, run through the passes the translation runs (the info pass among them)
struct OneBlock {
    ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    IR::Program program;
    FixtureEnvironment env;
    explicit OneBlock(Stage stage) : env(stage) {
        program.stage = stage;
        program.workgroup_size = {1, 1, 1};
        program.blocks.push_back(&block);
        program.post_order_blocks.push_back(&block);
        IR::AbstractSyntaxNode node{};
        node.type = IR::AbstractSyntaxNode::Type::Block;
        node.data.block = &block;
        program.syntax_list.push_back(node);
        IR::AbstractSyntaxNode ret{};
        ret.type = IR::AbstractSyntaxNode::Type::Return;
        program.syntax_list.push_back(ret);
    }
    void passes() {
        Optimization::SsaRewritePass(program);
        Optimization::ConstantPropagationPass(env, program);
        Optimization::DeadCodeEliminationPass(program);
        Optimization::IdentityRemovalPass(program);
        Optimization::CollectShaderInfoPass(env, program);
    }
};

// ---- LDC: index bits 36..40, mode 44..45, size 48..50 (B32 = 4), source register 8..15 (RZ = 255), destination 0..7 ----
static u64 ldc(u64 index, u64 mode = 0) { return (index << 36) | (mode << 44) | (u64{4} << 48) | (u64{255} << 8) | 1; }
static void translate_ldc(u64 index, u64 mode = 0) {
    OneBlock b(Stage::Compute);
    Maxwell::TranslatorVisitor visitor{b.env, b.block};
    visitor.LDC(ldc(index, mode));
    visitor.ir.WriteShared(32, visitor.ir.Imm32(0), visitor.X(static_cast<IR::Reg>(1)));
    visitor.ir.Epilogue();
    b.passes();
}
/// A constant buffer read whose index is an immediate, as LDC's IS mode leaves it once constant folding is done
static void info_pass_cbuf(u32 index) {
    OneBlock b(Stage::Compute);
    IR::IREmitter ir{b.block};
    const IR::U32 value{ir.GetCbuf(ir.Imm32(index), ir.Imm32(0), 32, false)};
    ir.WriteShared(32, ir.Imm32(0), value);
    ir.Epilogue();
    b.passes();
}

// ---- ISBERD: source register 8..15 (RZ: the immediate alone), o 32, skew 31, size 36..39, shift 47..48 ----
static u64 isberd(u64 src, u64 o, u64 skew, u64 sz, u64 shift) {
    return 1 | (src << 8) | (skew << 31) | (o << 32) | (sz << 36) | (shift << 47);
}
static void translate_isberd(u64 insn) {
    OneBlock b(Stage::Compute);
    Maxwell::TranslatorVisitor visitor{b.env, b.block};
    visitor.ISBERD(insn);
}

// ---- transform feedback: generic 0 stored by a vertex stage, its varying `components` wide ----
static void emit_xfb(u32 components) {
    OneBlock b(Stage::VertexB);
    IR::IREmitter ir{b.block};
    for (int c = 0; c < 4; c++)
        ir.SetAttribute(static_cast<IR::Attribute>(static_cast<size_t>(IR::Attribute::Generic0X) + c), ir.Imm32(1.0f), ir.Imm32(0));
    ir.Epilogue();
    b.passes();
    RuntimeInfo info{};
    const size_t at{static_cast<size_t>(IR::Attribute::Generic0X)};
    info.xfb_varyings[at] = TransformFeedbackVarying{.buffer = 0, .stream = 0, .stride = 16, .offset = 0, .components = components};
    info.xfb_count = static_cast<u32>(at + 4);
    Profile profile{};
    profile.supported_spirv = 0x00010600;
    Backend::Bindings bindings{};
    const auto spv = Backend::SPIRV::EmitSPIRV(profile, info, b.program, bindings);
    if (spv.size() <= 5) throw std::runtime_error("no module");
}

int main() {
    std::setvbuf(stdout, nullptr, _IONBF, 0);   // (each line out at once: a build that dies on a case still shows the ones before)
    expect(false, "LDC index 17, the last buffer", [] { translate_ldc(17); });
    expect(true, "LDC index 18", [] { translate_ldc(18); });
    expect(true, "LDC index 31", [] { translate_ldc(31); });
    expect(true, "LDC index 31 in IS mode", [] { translate_ldc(31, 2); });
    expect(false, "a constant buffer read at immediate index 17", [] { info_pass_cbuf(17); });
    expect(true, "a constant buffer read at immediate index 18 (the info pass)", [] { info_pass_cbuf(18); });
    expect(true, "a constant buffer read at immediate index 31 (the info pass)", [] { info_pass_cbuf(31); });
    expect(true, "a constant buffer read at immediate index 40 (1U << index past 32)", [] { info_pass_cbuf(40); });

    expect(false, "ISBERD shift 2 (B32)", [] { translate_isberd(isberd(2, 0, 0, 2, 2)); });
    expect(true, "ISBERD shift 3", [] { translate_isberd(isberd(2, 0, 0, 2, 3)); });
    expect(false, "ISBERD.O size 2 (U32)", [] { translate_isberd(isberd(255, 1, 0, 2, 0)); });
    for (u64 sz = 4; sz < 16; sz++) {
        const std::string what = "ISBERD.O size " + std::to_string(sz);
        expect(true, what.c_str(), [sz] { translate_isberd(isberd(255, 1, 0, sz, 0)); });
        const std::string skew = "ISBERD.O.SKEW size " + std::to_string(sz);
        expect(true, skew.c_str(), [sz] { translate_isberd(isberd(255, 1, 1, sz, 0)); });
    }

    expect(false, "a 4-component transform feedback varying", [] { emit_xfb(4); });
    expect(true, "a 5-component transform feedback varying", [] { emit_xfb(5); });
    expect(true, "a 255-component transform feedback varying", [] { emit_xfb(255); });

    std::printf("%d passed, %d failed\n", passes, failures);
    return failures ? 1 : 0;
}
