// SPDX-License-Identifier: GPL-3.0-or-later
// (LaküenRecomp) The Fog density and Brightness rows: a visual workaround, not a fix, for the white haze some places show (the
// cause is open upstream too, docs/design.md). From Orchid (MythosOfs/Orchid, src/shader_recompiler/ir_opt/
// oot_visual_workaround.h, GPL-3.0), as Hookshot had it until 2026-11-11 (removed in #2042 with its factors, 0.08 and 1.0, tuned
// against bugs fixed since), matched by the IR's shape, not by shader hashes:
//  - fog: the one compute shader with an add of 2^x and -2^y, the fog integration: its slice distance scaled before the extinction
//    and scattering accumulation (thinner fog everywhere, interiors too);
//  - brightness: a fragment shader with three loads of c3+0x38, the final pass's exposure before its filmic curve.
// 1.0 (100 %, the default): no edit at all.
#pragma once

#include <utility>
#include <vector>

#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/frontend/ir/program.h"

namespace Shader::Optimization {

/// The edits made (0: not such a shader, or the factor for its kind is 1)
inline size_t ApplyFogBrightness(IR::Program& program, f32 fog_scale, f32 exposure_scale) {
    const bool fog = program.stage == Stage::Compute && fog_scale != 1.0f;
    const bool exposure = program.stage == Stage::Fragment && exposure_scale != 1.0f;
    if (!fog && !exposure) return 0;
    const auto has_opcode = [](const IR::Value& value, IR::Opcode opcode) {
        return !value.IsImmediate() && value.InstRecursive()->GetOpcode() == opcode;
    };
    const auto negative_exp = [&](const IR::Value& value) {
        if (has_opcode(value, IR::Opcode::FPNeg32)) {
            return has_opcode(value.InstRecursive()->Arg(0), IR::Opcode::FPExp2);
        }
        if (!has_opcode(value, IR::Opcode::BitCastF32U32)) return false;
        const auto bits = value.InstRecursive()->Arg(0);
        if (!has_opcode(bits, IR::Opcode::BitwiseXor32)) return false;
        const auto* flip = bits.InstRecursive();
        const auto source = flip->Arg(0);
        return flip->Arg(1).IsImmediate() && flip->Arg(1).U32() == 0x80000000U &&
               has_opcode(source, IR::Opcode::BitCastU32F32) &&
               has_opcode(source.InstRecursive()->Arg(0), IR::Opcode::FPExp2);
    };
    std::vector<std::pair<IR::Block*, IR::Inst*>> matches;
    for (IR::Block* block : program.blocks) {
        for (IR::Inst& inst : block->Instructions()) {
            if (fog && inst.GetOpcode() == IR::Opcode::FPAdd32 &&
                ((negative_exp(inst.Arg(0)) && has_opcode(inst.Arg(1), IR::Opcode::FPExp2)) ||
                 (negative_exp(inst.Arg(1)) && has_opcode(inst.Arg(0), IR::Opcode::FPExp2)))) {
                matches.emplace_back(block, &inst);
            }
            if (exposure && inst.GetOpcode() == IR::Opcode::GetCbufF32 && inst.Arg(0).IsImmediate() &&
                inst.Arg(0).U32() == 3 && inst.Arg(1).IsImmediate() && inst.Arg(1).U32() == 0x38) {
                matches.emplace_back(block, &inst);
            }
        }
    }
    if (matches.size() != (fog ? 1u : 3u)) return 0;
    for (const auto& [block, inst] : matches) {
        const auto insertion = block->Instructions().iterator_to(*inst);
        const auto original = block->PrependNewInst(insertion, *inst);
        IR::IREmitter ir{*block, insertion};
        const auto scaled = ir.FPMul(IR::F32{IR::Value{&*original}}, ir.Imm32(fog ? fog_scale : exposure_scale));
        inst->ReplaceUsesWith(scaled);
    }
    return matches.size();
}

} // namespace Shader::Optimization
