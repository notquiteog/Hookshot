# Malformed shader input is refused

A broken or malicious mod, or a game bug, can hand the shader recompiler instruction fields and runtime data the hardware
never encodes. This game-free fixture authors them, calls the production translators and passes
(`gpu/vk/eden/shader_recompiler`), and expects each to end in `Shader::NotImplementedException`, which the translation's
callers catch (`gpu/vk/vk_shader.cpp`: the program is left out and logged), while the well-formed neighbour of each still
translates:

- LDC's 5-bit constant buffer index past the 18 buffers (18, 31, and 31 in IS mode), and a constant buffer read whose
  index is an immediate past them (18, 31, 40), as constant folding leaves LDC's IS mode: the info pass wrote
  `constant_buffer_used_sizes[index]` past its end and shifted `1U << index`;
- ISBERD's 2-bit shift at 3 and 4-bit size at 4..15, which reached `UNREACHABLE` (then `__builtin_unreachable`);
- a transform feedback varying of 5 or 255 components at a location's first element, which wrote past
  `output_generics[index]`'s 4 elements.

No game, dump, GPU or driver is used. On main before the fix the LDC, info pass and varying cases are accepted (the writes
past the arrays go unnoticed) and the ISBERD cases run into undefined behaviour.

```sh
CC=clang CXX=clang++ cmake -S tests/malformed_shaders -B build-malformed \
  -DREPO_ROOT="$PWD" -DSPIRV_HEADERS_ROOT=/path/to/SPIRV-Headers
cmake --build build-malformed --parallel 2
build-malformed/malformed_shaders
```
