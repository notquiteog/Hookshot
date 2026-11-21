// (hookshot) vk_signed.h: a vendor's library loaded only when it is the vendor's own file, and the file that was checked.
#include "vk_signed.h"

#include "vk_internal.h"   // (logf)

#ifdef _WIN32
#include <softpub.h>
#include <wincrypt.h>
#include <wintrust.h>

#include <cwchar>
#include <vector>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace mkwvk::signed_dll {

#ifdef _WIN32
namespace {
std::string narrow(const wchar_t* w) {   // (for the log: UTF-8, never the ANSI code page)
    std::string out;
    const int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    if (n > 1) {
        out.resize((size_t)n - 1);
        WideCharToMultiByte(CP_UTF8, 0, w, -1, out.data(), n, nullptr, nullptr);
    }
    return out;
}

/// Whether Windows trusts the file's embedded signature and its signer's name is exactly `signer`.
///
/// Written out here rather than taken from Streamline's own sl_security.h on purpose: that header's verifyEmbeddedSignature
/// uses WINTRUST_SIGNATURE_SETTINGS, which the Windows SDK has and llvm-mingw's headers do not, and Hookshot builds for
/// Windows with either (third_party/a64-kit). This uses only what both have. Trust alone is not enough -- it would accept
/// anything signed by anyone Windows trusts -- so the subject name is read too.
bool signed_by(const std::wstring& path, const wchar_t* signer, const char* what) {
    WINTRUST_FILE_INFO file{};
    file.cbStruct = sizeof file;
    file.pcwszFilePath = path.c_str();
    GUID action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    WINTRUST_DATA data{};
    data.cbStruct = sizeof data;
    data.dwUIChoice = WTD_UI_NONE;
    data.fdwRevocationChecks = WTD_REVOKE_NONE;   // (a player may well be offline)
    data.dwUnionChoice = WTD_CHOICE_FILE;
    data.pFile = &file;
    data.dwStateAction = WTD_STATEACTION_VERIFY;
    const LONG status = WinVerifyTrust(nullptr, &action, &data);
    data.dwStateAction = WTD_STATEACTION_CLOSE;
    WinVerifyTrust(nullptr, &action, &data);
    if (status != ERROR_SUCCESS) {
        logf("vk: %s has no signature Windows trusts (status %#lx): not loading it", what, (unsigned long)status);
        return false;
    }
    HCERTSTORE store{};
    HCRYPTMSG msg{};
    if (!CryptQueryObject(CERT_QUERY_OBJECT_FILE, path.c_str(), CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED,
                          CERT_QUERY_FORMAT_FLAG_BINARY, 0, nullptr, nullptr, nullptr, &store, &msg, nullptr)) {
        logf("vk: %s's signature could not be read (error %lu): not loading it", what, GetLastError());
        return false;
    }
    bool ok = false;
    DWORD info_size = 0;
    if (CryptMsgGetParam(msg, CMSG_SIGNER_INFO_PARAM, 0, nullptr, &info_size) && info_size) {
        std::vector<unsigned char> buffer(info_size);
        if (CryptMsgGetParam(msg, CMSG_SIGNER_INFO_PARAM, 0, buffer.data(), &info_size)) {
            const auto* info = reinterpret_cast<CMSG_SIGNER_INFO*>(buffer.data());
            CERT_INFO want{};
            want.Issuer = info->Issuer;
            want.SerialNumber = info->SerialNumber;
            if (PCCERT_CONTEXT cert = CertFindCertificateInStore(store, X509_ASN_ENCODING, 0, CERT_FIND_SUBJECT_CERT, &want,
                                                                 nullptr)) {
                wchar_t name[256] = {};
                CertGetNameStringW(cert, CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, nullptr, name, 256);
                // (exactly the vendor's name: a certificate whose name only contains it is anyone's)
                ok = wcscmp(name, signer) == 0;
                if (!ok)
                    logf("vk: %s is signed by \"%s\", not \"%s\": not loading it", what, narrow(name).c_str(),
                         narrow(signer).c_str());
                CertFreeCertificateContext(cert);
            }
        }
    }
    CryptMsgClose(msg);
    CertCloseStore(store, 0);
    return ok;
}
}  // namespace

std::wstring wide(const std::string& utf8) {
    std::wstring out;
    const int n = MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), nullptr, 0);
    if (n > 0) {
        out.resize((size_t)n);
        MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), out.data(), n);
    }
    return out;
}

HANDLE open_checked(const std::wstring& path, const wchar_t* signer, const char* what) {
    // (held from before the check until the caller has loaded it, sharing reads only: the file checked is the file loaded)
    const HANDLE held = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                    FILE_ATTRIBUTE_NORMAL, nullptr);
    if (held == INVALID_HANDLE_VALUE) {
        logf("vk: could not open %s to check it (error %lu)", what, GetLastError());
        return INVALID_HANDLE_VALUE;
    }
    if (!signed_by(path, signer, what)) {
        CloseHandle(held);
        return INVALID_HANDLE_VALUE;
    }
    return held;
}

HMODULE load(const std::wstring& path, const wchar_t* signer, const char* what, DWORD flags) {
    const HANDLE held = open_checked(path, signer, what);
    if (held == INVALID_HANDLE_VALUE) {
        SetLastError(ERROR_INVALID_IMAGE_HASH);
        return nullptr;
    }
    HMODULE m = LoadLibraryExW(path.c_str(), nullptr, flags);
    const DWORD error = m ? 0 : GetLastError();
    CloseHandle(held);
    if (!m) SetLastError(error);
    return m;
}
#else
namespace {
/// One file or folder: this user's or root's, and writable by its owner alone, or by its group when that group is this
/// user's own (a user-private group: Ubuntu and its kin make files 664 and folders 775 for every user, umask 002)
bool safe(const std::string& p, const char* what, const char* kind) {
    struct stat st{};
    if (stat(p.c_str(), &st) != 0) {
        logf("vk: %s: %s %s could not be read: not loading it", what, kind, p.c_str());
        return false;
    }
    if (st.st_uid != geteuid() && st.st_uid != 0) {
        logf("vk: %s: %s %s belongs to another account (uid %u): not loading it", what, kind, p.c_str(), (unsigned)st.st_uid);
        return false;
    }
    const bool own_group = st.st_gid == getegid();
    if ((st.st_mode & S_IWOTH) || ((st.st_mode & S_IWGRP) && !own_group)) {
        logf("vk: %s: %s %s can be written by other accounts (mode %03o): not loading it", what, kind, p.c_str(),
             (unsigned)(st.st_mode & 0777));
        return false;
    }
    return true;
}
}  // namespace

bool owned_safely(const std::string& path, const char* what) {
    const size_t cut = path.find_last_of('/');
    const std::string dir = cut == std::string::npos ? std::string(".") : cut == 0 ? std::string("/") : path.substr(0, cut);
    return safe(path, what, "the file") && safe(dir, what, "its folder");
}
#endif

}  // namespace mkwvk::signed_dll
