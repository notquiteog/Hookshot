// (hookshot) Loading another company's library from a folder the player can write to: NVIDIA's Streamline interposer
// (vk_streamline.cpp), AMD's FidelityFX loader (vk_fsr4.cpp, vk_ffx.cpp). Only the vendor's own file is loaded, and it is
// the file that was checked.
//
// Windows: the file is held open, sharing reads only (nothing can write, rename or delete it), from before its signature is
// checked until the caller has loaded it; Windows must trust the signature (WinVerifyTrust) and the signing certificate's
// name must be exactly the vendor's: "NVIDIA Corporation", "Advanced Micro Devices" (the names in their certificates' CN,
// read from NVIDIA's sl.interposer.dll and AMD's amd_fidelityfx_*_vk.dll on 2026-11-21; a name that only contains the
// vendor's is anyone's).
// Linux: shared objects are not signed, so the file and its folder must belong to the player (or root) and be writable by
// nobody else (its group may write when that group is the player's own: Ubuntu's 775 folders): a library another account
// could have put there is not loaded.
#pragma once

#include <string>

#ifdef _WIN32
#include <windows.h>
#endif

namespace mkwvk::signed_dll {

#ifdef _WIN32
inline constexpr const wchar_t* kNvidia = L"NVIDIA Corporation";
inline constexpr const wchar_t* kAmd = L"Advanced Micro Devices";

/// A UTF-8 path (the executable's manifest makes narrow paths UTF-8: nx2/win_manifest.py) as Windows' wide one
std::wstring wide(const std::string& utf8);

/// `path` opened sharing reads only, once Windows trusts its signature and its signer is exactly `signer`; the caller loads
/// it while the handle is held and closes it after. INVALID_HANDLE_VALUE, with one line logged naming `what`, when not.
HANDLE open_checked(const std::wstring& path, const wchar_t* signer, const char* what);

/// open_checked, then LoadLibraryExW with `flags` (the caller's search: LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR and System32 or the
/// default folders), then the handle let go. nullptr when it is not the vendor's file or did not load (GetLastError then).
HMODULE load(const std::wstring& path, const wchar_t* signer, const char* what, DWORD flags);
#else
/// Whether `path` and its folder belong to this user or root and no one else may write either (the log says why not).
bool owned_safely(const std::string& path, const char* what);
#endif

}  // namespace mkwvk::signed_dll
