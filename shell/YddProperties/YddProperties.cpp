#define NOMINMAX
#include <windows.h>
#include <propsys.h>
#include <propvarutil.h>
#include <shobjidl.h>
#include <shlwapi.h>

#include <algorithm>
#include <cstdint>
#include <cwctype>
#include <fstream>
#include <limits>
#include <new>
#include <string>
#include <vector>

// {B1A5424D-716D-4F75-9ED2-9AC539A8D4C1}
static const CLSID CLSID_YddPropertyHandler =
{0xb1a5424d, 0x716d, 0x4f75, {0x9e, 0xd2, 0x9a, 0xc5, 0x39, 0xa8, 0xd4, 0xc1}};

// YTDPreviewer.AssociatedYtdCount: {761DA6FA-CC69-4F1F-AF39-1415E219AABB}, 2
static const PROPERTYKEY PKEY_YddAssociatedYtdCount =
{{0x761da6fa, 0xcc69, 0x4f1f, {0xaf, 0x39, 0x14, 0x15, 0xe2, 0x19, 0xaa, 0xbb}}, 2};

static HMODULE g_module = nullptr;
static volatile LONG g_objects = 0;
static volatile LONG g_locks = 0;

namespace {

constexpr std::uint32_t kRsc7Magic = 0x37435352;
constexpr std::uint64_t kVirtualBase = 0x50000000ULL;

template <typename T>
bool ReadAt(const std::vector<std::uint8_t>& data, std::size_t offset, T* value)
{
    if (!value || offset > data.size() || sizeof(T) > data.size() - offset)
        return false;
    memcpy(value, data.data() + offset, sizeof(T));
    return true;
}

bool VirtualOffset(std::uint64_t pointer, std::size_t size, std::size_t* offset)
{
    if (!offset || pointer < kVirtualBase)
        return false;
    const auto raw = pointer - kVirtualBase;
    if (raw >= size || raw > std::numeric_limits<std::size_t>::max())
        return false;
    *offset = static_cast<std::size_t>(raw);
    return true;
}

std::wstring Lowercase(std::wstring value)
{
    std::transform(value.begin(), value.end(), value.begin(), towlower);
    return value;
}

bool IsThreeDigits(const std::wstring& value, std::size_t offset)
{
    return offset + 3 <= value.size() &&
        iswdigit(value[offset]) &&
        iswdigit(value[offset + 1]) &&
        iswdigit(value[offset + 2]);
}

void ParseYddIdentity(
    const std::wstring& file_stem,
    std::wstring* component,
    std::wstring* index)
{
    const std::wstring stem = Lowercase(file_stem);
    component->clear();
    index->clear();
    for (std::size_t pos = stem.size(); pos-- > 0;) {
        if (stem[pos] != L'_' || !IsThreeDigits(stem, pos + 1))
            continue;
        const std::size_t after = pos + 4;
        if (after != stem.size() &&
            !(after + 2 == stem.size() && stem[after] == L'_' && iswalpha(stem[after + 1])))
            continue;
        *component = stem.substr(0, pos);
        *index = stem.substr(pos + 1, 3);
        return;
    }
    const std::size_t separator = stem.find(L'_');
    *component = stem.substr(0, separator);
}

bool YtdMatchesYdd(
    const std::wstring& ytd_stem,
    const std::wstring& ydd_stem,
    const std::wstring& component,
    const std::wstring& index)
{
    const std::wstring candidate = Lowercase(ytd_stem);
    if (candidate == ydd_stem)
        return true;
    const std::wstring prefix = component + L"_";
    if (candidate.rfind(prefix, 0) != 0)
        return false;
    if (index.empty())
        return true;

    const std::wstring token = L"_" + index;
    std::size_t pos = candidate.find(token, prefix.size() - 1);
    while (pos != std::wstring::npos) {
        const std::size_t after = pos + token.size();
        if (after == candidate.size() || candidate[after] == L'_')
            return true;
        pos = candidate.find(token, pos + 1);
    }
    return false;
}

HRESULT CountAssociatedYtdFiles(const wchar_t* ydd_path, std::uint32_t* count)
{
    if (!ydd_path || !*ydd_path || !count)
        return E_INVALIDARG;

    wchar_t full_path[32768] = {};
    if (!GetFullPathNameW(ydd_path, ARRAYSIZE(full_path), full_path, nullptr))
        return HRESULT_FROM_WIN32(GetLastError());

    wchar_t folder[32768] = {};
    wchar_t stem_buffer[32768] = {};
    wcscpy_s(folder, full_path);
    wcscpy_s(stem_buffer, PathFindFileNameW(full_path));
    PathRemoveExtensionW(stem_buffer);
    if (!PathRemoveFileSpecW(folder))
        return HRESULT_FROM_WIN32(ERROR_INVALID_NAME);

    const std::wstring ydd_stem = Lowercase(stem_buffer);
    std::wstring component;
    std::wstring index;
    ParseYddIdentity(ydd_stem, &component, &index);

    std::wstring pattern = std::wstring(folder) + L"\\*.ytd";
    WIN32_FIND_DATAW entry = {};
    HANDLE find = FindFirstFileW(pattern.c_str(), &entry);
    if (find == INVALID_HANDLE_VALUE) {
        const DWORD error = GetLastError();
        if (error == ERROR_FILE_NOT_FOUND) {
            *count = 0;
            return S_OK;
        }
        return HRESULT_FROM_WIN32(error);
    }

    std::uint32_t total = 0;
    do {
        if (entry.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            continue;
        wchar_t ytd_stem_buffer[MAX_PATH] = {};
        wcscpy_s(ytd_stem_buffer, entry.cFileName);
        PathRemoveExtensionW(ytd_stem_buffer);
        if (YtdMatchesYdd(ytd_stem_buffer, ydd_stem, component, index))
            ++total;
    } while (FindNextFileW(find, &entry));
    FindClose(find);
    *count = total;
    return S_OK;
}

std::size_t ResourceSizeFromFlags(std::uint32_t flags)
{
    const std::uint64_t units =
        (((flags >> 27) & 0x1ULL) << 0) +
        (((flags >> 26) & 0x1ULL) << 1) +
        (((flags >> 25) & 0x1ULL) << 2) +
        (((flags >> 24) & 0x1ULL) << 3) +
        (((flags >> 17) & 0x7FULL) << 4) +
        (((flags >> 11) & 0x3FULL) << 5) +
        (((flags >> 7) & 0xFULL) << 6) +
        (((flags >> 5) & 0x3ULL) << 7) +
        (((flags >> 4) & 0x1ULL) << 8);
    const std::uint64_t base = 0x200ULL << (flags & 0xF);
    const std::uint64_t result = base * units;
    return result <= std::numeric_limits<std::size_t>::max()
        ? static_cast<std::size_t>(result)
        : 0;
}

struct ZStream {
    unsigned char* next_in;
    unsigned int avail_in;
    unsigned long total_in;
    unsigned char* next_out;
    unsigned int avail_out;
    unsigned long total_out;
    char* msg;
    void* state;
    void* zalloc;
    void* zfree;
    void* opaque;
    int data_type;
    unsigned long adler;
    unsigned long reserved;
};

using InflateInit2 = int (__cdecl*)(ZStream*, int, const char*, int);
using Inflate = int (__cdecl*)(ZStream*, int);
using InflateEnd = int (__cdecl*)(ZStream*);
using ZlibVersion = const char* (__cdecl*)();

bool ModuleDirectory(std::wstring* directory)
{
    if (!directory || !g_module)
        return false;
    wchar_t path[MAX_PATH] = {};
    const DWORD length = GetModuleFileNameW(g_module, path, ARRAYSIZE(path));
    if (!length || length >= ARRAYSIZE(path))
        return false;
    PathRemoveFileSpecW(path);
    *directory = path;
    return true;
}

bool InflateRscPayload(
    const std::vector<std::uint8_t>& compressed,
    std::size_t output_size,
    std::vector<std::uint8_t>* output)
{
    if (!output || compressed.size() <= 16 || output_size == 0 ||
        compressed.size() - 16 > std::numeric_limits<unsigned int>::max() ||
        output_size > std::numeric_limits<unsigned int>::max())
        return false;

    std::wstring directory;
    if (!ModuleDirectory(&directory))
        return false;
    const std::wstring zlib_path = directory + L"\\_internal\\zlib1.dll";
    HMODULE zlib = LoadLibraryExW(zlib_path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR);
    if (!zlib)
        return false;

    const auto init = reinterpret_cast<InflateInit2>(GetProcAddress(zlib, "inflateInit2_"));
    const auto inflate = reinterpret_cast<Inflate>(GetProcAddress(zlib, "inflate"));
    const auto finish = reinterpret_cast<InflateEnd>(GetProcAddress(zlib, "inflateEnd"));
    const auto version = reinterpret_cast<ZlibVersion>(GetProcAddress(zlib, "zlibVersion"));
    if (!init || !inflate || !finish || !version) {
        FreeLibrary(zlib);
        return false;
    }

    output->assign(output_size, 0);
    ZStream stream = {};
    stream.next_in = const_cast<unsigned char*>(compressed.data() + 16);
    stream.avail_in = static_cast<unsigned int>(compressed.size() - 16);
    stream.next_out = output->data();
    stream.avail_out = static_cast<unsigned int>(output->size());

    constexpr int kNoFlush = 0;
    constexpr int kStreamEnd = 1;
    bool ok = init(&stream, -15, version(), sizeof(stream)) == 0;
    if (ok) {
        int status = 0;
        do {
            status = inflate(&stream, kNoFlush);
        } while (status == 0 && stream.avail_out > 0);
        ok = status == kStreamEnd && stream.total_out >= output_size;
        finish(&stream);
    }
    FreeLibrary(zlib);
    return ok;
}

bool CountEmbeddedTextures(
    const std::vector<std::uint8_t>& file_data,
    std::uint32_t* texture_count)
{
    if (!texture_count || file_data.size() < 16)
        return false;

    std::uint32_t magic = 0, system_flags = 0, graphics_flags = 0;
    if (!ReadAt(file_data, 0, &magic) || magic != kRsc7Magic ||
        !ReadAt(file_data, 8, &system_flags) ||
        !ReadAt(file_data, 12, &graphics_flags))
        return false;

    const std::size_t system_size = ResourceSizeFromFlags(system_flags);
    const std::size_t graphics_size = ResourceSizeFromFlags(graphics_flags);
    if (!system_size || graphics_size > std::numeric_limits<std::size_t>::max() - system_size)
        return false;

    std::vector<std::uint8_t> payload;
    if (!InflateRscPayload(file_data, system_size + graphics_size, &payload) ||
        payload.size() < system_size || system_size < 0x3A)
        return false;

    std::uint64_t drawables_pointer = 0;
    std::uint16_t drawables_count = 0;
    if (!ReadAt(payload, 0x30, &drawables_pointer) ||
        !ReadAt(payload, 0x38, &drawables_count) ||
        drawables_count > 0x4000)
        return false;

    if (!drawables_pointer || !drawables_count) {
        *texture_count = 0;
        return true;
    }

    std::size_t pointer_table = 0;
    if (!VirtualOffset(drawables_pointer, system_size, &pointer_table) ||
        pointer_table > system_size ||
        static_cast<std::size_t>(drawables_count) * 8 > system_size - pointer_table)
        return false;

    std::uint64_t total = 0;
    for (std::uint16_t index = 0; index < drawables_count; ++index) {
        std::uint64_t drawable_pointer = 0;
        if (!ReadAt(payload, pointer_table + static_cast<std::size_t>(index) * 8, &drawable_pointer))
            return false;
        if (!drawable_pointer)
            continue;

        std::size_t drawable = 0;
        if (!VirtualOffset(drawable_pointer, system_size, &drawable) ||
            drawable > system_size - 0x18)
            return false;
        const std::size_t root = drawable + 0x10;

        std::uint64_t shader_group_pointer = 0;
        if (!ReadAt(payload, root, &shader_group_pointer) || !shader_group_pointer)
            continue;
        std::size_t shader_group = 0;
        if (!VirtualOffset(shader_group_pointer, system_size, &shader_group) ||
            shader_group > system_size - 0x10)
            return false;

        std::uint64_t dictionary_pointer = 0;
        if (!ReadAt(payload, shader_group + 0x08, &dictionary_pointer) || !dictionary_pointer)
            continue;
        std::size_t dictionary = 0;
        if (!VirtualOffset(dictionary_pointer, system_size, &dictionary) ||
            dictionary > system_size - 0x3A)
            return false;

        std::uint16_t count = 0;
        std::uint64_t items_pointer = 0;
        if (!ReadAt(payload, dictionary + 0x28, &count) ||
            !ReadAt(payload, dictionary + 0x30, &items_pointer) ||
            count > 0x4000)
            return false;
        std::size_t items = 0;
        if (count && (!VirtualOffset(items_pointer, system_size, &items) ||
            static_cast<std::size_t>(count) * 8 > system_size - items))
            return false;
        total += count;
    }

    if (total > std::numeric_limits<std::uint32_t>::max())
        return false;
    *texture_count = static_cast<std::uint32_t>(total);
    return true;
}

HRESULT ReadStream(IStream* stream, std::vector<std::uint8_t>* data)
{
    if (!stream || !data)
        return E_INVALIDARG;
    STATSTG stat = {};
    HRESULT hr = stream->Stat(&stat, STATFLAG_NONAME);
    if (FAILED(hr))
        return hr;
    if (stat.cbSize.QuadPart == 0 ||
        stat.cbSize.QuadPart > std::numeric_limits<unsigned int>::max())
        return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);

    LARGE_INTEGER zero = {};
    hr = stream->Seek(zero, STREAM_SEEK_SET, nullptr);
    if (FAILED(hr))
        return hr;

    data->assign(static_cast<std::size_t>(stat.cbSize.QuadPart), 0);
    ULONG total = 0;
    while (static_cast<std::size_t>(total) < data->size()) {
        ULONG read = 0;
        const ULONG request = static_cast<ULONG>(
            std::min<std::size_t>(data->size() - total, 1024 * 1024));
        hr = stream->Read(data->data() + total, request, &read);
        if (FAILED(hr))
            return hr;
        if (!read)
            break;
        total += read;
    }
    if (total != data->size())
        return STG_E_READFAULT;
    return S_OK;
}

HRESULT SetRegistryString(HKEY root, const wchar_t* subkey, const wchar_t* name, const wchar_t* value)
{
    HKEY key = nullptr;
    LONG status = RegCreateKeyExW(root, subkey, 0, nullptr, 0, KEY_WRITE, nullptr, &key, nullptr);
    if (status != ERROR_SUCCESS)
        return HRESULT_FROM_WIN32(status);
    const DWORD bytes = static_cast<DWORD>((wcslen(value) + 1) * sizeof(wchar_t));
    status = RegSetValueExW(key, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(value), bytes);
    RegCloseKey(key);
    return HRESULT_FROM_WIN32(status);
}

} // namespace

class YddPropertyHandler final :
    public IPropertyStore,
    public IPropertyStoreCapabilities,
    public IInitializeWithFile
{
public:
    YddPropertyHandler() : refs_(1), initialized_(false), ytd_count_(0)
    {
        InterlockedIncrement(&g_objects);
    }

    ~YddPropertyHandler()
    {
        InterlockedDecrement(&g_objects);
    }

    IFACEMETHODIMP QueryInterface(REFIID iid, void** object) override
    {
        if (!object)
            return E_POINTER;
        *object = nullptr;
        if (iid == IID_IUnknown || iid == IID_IPropertyStore)
            *object = static_cast<IPropertyStore*>(this);
        else if (iid == IID_IPropertyStoreCapabilities)
            *object = static_cast<IPropertyStoreCapabilities*>(this);
        else if (iid == IID_IInitializeWithFile)
            *object = static_cast<IInitializeWithFile*>(this);
        else
            return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }

    IFACEMETHODIMP_(ULONG) Release() override
    {
        const ULONG refs = InterlockedDecrement(&refs_);
        if (!refs)
            delete this;
        return refs;
    }

    IFACEMETHODIMP Initialize(LPCWSTR file_path, DWORD mode) override
    {
        if (initialized_)
            return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if ((mode & STGM_READWRITE) || (mode & STGM_WRITE))
            return STG_E_ACCESSDENIED;
        initialized_ = true;
        return CountAssociatedYtdFiles(file_path, &ytd_count_);
    }

    IFACEMETHODIMP GetCount(DWORD* count) override
    {
        if (!count)
            return E_POINTER;
        *count = 1;
        return S_OK;
    }

    IFACEMETHODIMP GetAt(DWORD index, PROPERTYKEY* key) override
    {
        if (!key)
            return E_POINTER;
        if (index != 0)
            return E_INVALIDARG;
        *key = PKEY_YddAssociatedYtdCount;
        return S_OK;
    }

    IFACEMETHODIMP GetValue(REFPROPERTYKEY key, PROPVARIANT* value) override
    {
        if (!value)
            return E_POINTER;
        PropVariantInit(value);
        if (key != PKEY_YddAssociatedYtdCount)
            return S_FALSE;
        return InitPropVariantFromUInt32(ytd_count_, value);
    }

    IFACEMETHODIMP SetValue(REFPROPERTYKEY, REFPROPVARIANT) override { return STG_E_ACCESSDENIED; }
    IFACEMETHODIMP Commit() override { return S_OK; }
    IFACEMETHODIMP IsPropertyWritable(REFPROPERTYKEY) override { return S_FALSE; }

private:
    LONG refs_;
    bool initialized_;
    std::uint32_t ytd_count_;
};

class ClassFactory final : public IClassFactory
{
public:
    ClassFactory() : refs_(1) {}

    IFACEMETHODIMP QueryInterface(REFIID iid, void** object) override
    {
        if (!object)
            return E_POINTER;
        *object = nullptr;
        if (iid == IID_IUnknown || iid == IID_IClassFactory)
            *object = static_cast<IClassFactory*>(this);
        else
            return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override
    {
        const ULONG refs = InterlockedDecrement(&refs_);
        if (!refs)
            delete this;
        return refs;
    }

    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** object) override
    {
        if (outer)
            return CLASS_E_NOAGGREGATION;
        auto* handler = new (std::nothrow) YddPropertyHandler();
        if (!handler)
            return E_OUTOFMEMORY;
        const HRESULT hr = handler->QueryInterface(iid, object);
        handler->Release();
        return hr;
    }

    IFACEMETHODIMP LockServer(BOOL lock) override
    {
        lock ? InterlockedIncrement(&g_locks) : InterlockedDecrement(&g_locks);
        return S_OK;
    }

private:
    LONG refs_;
};

extern "C" BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

extern "C" STDAPI DllCanUnloadNow()
{
    return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}

extern "C" STDAPI DllGetClassObject(REFCLSID clsid, REFIID iid, void** object)
{
    if (clsid != CLSID_YddPropertyHandler)
        return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) ClassFactory();
    if (!factory)
        return E_OUTOFMEMORY;
    const HRESULT hr = factory->QueryInterface(iid, object);
    factory->Release();
    return hr;
}

extern "C" STDAPI DllRegisterServer()
{
    wchar_t module_path[MAX_PATH] = {};
    if (!GetModuleFileNameW(g_module, module_path, ARRAYSIZE(module_path)))
        return HRESULT_FROM_WIN32(GetLastError());

    const wchar_t* clsid_path =
        L"Software\\Classes\\CLSID\\{B1A5424D-716D-4F75-9ED2-9AC539A8D4C1}";
    HRESULT hr = SetRegistryString(HKEY_LOCAL_MACHINE, clsid_path, nullptr, L"YTD Previewer YDD Property Handler");
    if (FAILED(hr))
        return hr;
    std::wstring inproc = std::wstring(clsid_path) + L"\\InprocServer32";
    hr = SetRegistryString(HKEY_LOCAL_MACHINE, inproc.c_str(), nullptr, module_path);
    if (FAILED(hr))
        return hr;
    hr = SetRegistryString(HKEY_LOCAL_MACHINE, inproc.c_str(), L"ThreadingModel", L"Apartment");
    if (FAILED(hr))
        return hr;
    return SetRegistryString(
        HKEY_LOCAL_MACHINE,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\.ydd",
        nullptr,
        L"{B1A5424D-716D-4F75-9ED2-9AC539A8D4C1}");
}

extern "C" STDAPI DllUnregisterServer()
{
    RegDeleteTreeW(
        HKEY_LOCAL_MACHINE,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\.ydd");
    RegDeleteTreeW(
        HKEY_LOCAL_MACHINE,
        L"Software\\Classes\\CLSID\\{B1A5424D-716D-4F75-9ED2-9AC539A8D4C1}");
    return S_OK;
}

extern "C" __declspec(dllexport) HRESULT WINAPI
YddGetTextureCountFromFile(const wchar_t* file_path, std::uint32_t* texture_count)
{
    if (!file_path || !texture_count)
        return E_INVALIDARG;
    std::ifstream file(file_path, std::ios::binary | std::ios::ate);
    if (!file)
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    const auto size = file.tellg();
    if (size <= 0 || static_cast<std::uint64_t>(size) > std::numeric_limits<unsigned int>::max())
        return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
    std::vector<std::uint8_t> data(static_cast<std::size_t>(size));
    file.seekg(0, std::ios::beg);
    if (!file.read(reinterpret_cast<char*>(data.data()), size))
        return STG_E_READFAULT;
    return CountEmbeddedTextures(data, texture_count)
        ? S_OK
        : HRESULT_FROM_WIN32(ERROR_BAD_FORMAT);
}

extern "C" __declspec(dllexport) HRESULT WINAPI
YddGetAssociatedYtdCountFromFile(const wchar_t* file_path, std::uint32_t* ytd_count)
{
    return CountAssociatedYtdFiles(file_path, ytd_count);
}
